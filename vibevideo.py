from sentence_transformers import SentenceTransformer
import faiss
import argparse
import numpy as np
import re
import subprocess
import os
import sys
import imageio_ffmpeg
from engines.audacity_engine import AudacityEngine
from mcp.instruction import find_mcp_instruction
from mcp.capability_resolver import resolve_tool
from engines.ffmpeg_engine import execute_ffmpeg
from mcp.executor import execute as execute_tool_instruction
from mcp.chroma_store import seed_collections, load_all_chunks

print("Python:", sys.executable)
print("CWD:", os.getcwd())

# path to ffmpeg binary
ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()

def scan_media_files(directory="."):
    """Scan current directory for media files and build working name mappings."""
    extensions = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".mp3", ".wav", ".png", ".jpg", ".jpeg"}
    files = [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f)) and os.path.splitext(f.lower())[1] in extensions]
    files.sort(key=lambda x: x.lower())
    
    mapping = {}
    for idx, filename in enumerate(files, start=1):
        mapping[f"file{idx}"] = filename
        mapping[f"f{idx}"] = filename
        mapping[f"[{idx}]"] = filename
    return files, mapping

def preprocess_query(query, mapping):
    """Replace working names like file1, f1, [1] or file 1 with actual file names."""
    # Normalize "file 1" -> "file1"
    query = re.sub(r'\bfile\s+(\d+)\b', r'file\1', query, flags=re.I)
    
    # Replace keys from longest to shortest
    def replace_func(match):
        word = match.group(0).lower()
        return mapping.get(word, match.group(0))
        
    # Match pattern: f\d+ or file\d+ but not followed by dot and extension
    query = re.sub(r'\b(file\d+|f\d+)\b(?!\s*\.(?:mp4|mkv|avi|mov|webm|mp3|wav|png|jpg|jpeg))', replace_func, query, flags=re.I)
    
    # Match pattern: \[\d+\] but not followed by dot and extension
    def replace_bracket(match):
        bracketed = match.group(0)
        return mapping.get(bracketed, match.group(0))
        
    query = re.sub(r'\[\d+\](?!\s*\.(?:mp4|mkv|avi|mov|webm|mp3|wav|png|jpg|jpeg))', replace_bracket, query)
    
    return query

# load model and build faiss index

print("Loading embedding model...")

model = SentenceTransformer('all-MiniLM-L6-v2')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Seed ChromaDB from documents/*.txt (no-op if already done)
print("Initialising ChromaDB...")
seed_collections()

# Load all capability chunks from ChromaDB and build FAISS index
chunks = load_all_chunks()

texts = [chunk["text"] for chunk in chunks]

embeddings = model.encode(texts)

dimension = embeddings.shape[1]

index = faiss.IndexFlatL2(dimension)

index.add(np.array(embeddings).astype("float32"))

print(f"FAISS index ready ({len(chunks)} entries from ChromaDB).\n")

# extract parameters from query

def parse_parameters(text):

    params = {
        "fps": 30,
        "duration": None,
        "filename": None,
        "input_files": [],
        "output_file": None,
        "width": None,
        "height": None,
        "start_time": None,
        "end_time": None,
        "transition": None,
        "speed_multiplier": 1.0,
        "volume_level": 1.0,
        "visual_type": "waveform",
        "fade_type": "in",
        "fade_duration": 3.0,
        "url": None,
        "quality": None,
        "delete_full": False,
        "layer_mode": "tile",     # tile | pip | blend
        "pip_position": "bottom-right",  # top-left | top-right | bottom-left | bottom-right
        "blend_opacity": 0.5,     # 0.0-1.0 weight of base (first) video in blend mode
    }

    # layer_mode: blend | pip | tile (default)
    if re.search(r'\b(blend|ghost|mix|transparent|opacity|see.?through)\b', text, re.I):
        params["layer_mode"] = "blend"
    elif re.search(r'\b(pip|picture.in.picture|corner|inset|small|miniature)\b', text, re.I):
        params["layer_mode"] = "pip"
    else:
        params["layer_mode"] = "tile"

    # blend_opacity: weight of the FIRST (base) video, e.g. "70%" → 0.7
    # Phrases: "70%", "70 percent", "opacity 70", "at 0.7"
    m_op = re.search(r'(\d+(?:\.\d+)?)\s*(?:%|percent)', text, re.I)
    if not m_op:
        m_op = re.search(r'\b(?:opacity|weight|alpha)\s+(\d+(?:\.\d+)?)', text, re.I)
    if m_op:
        val = float(m_op.group(1))
        # If >1 treat as percentage (70 → 0.7), else already a fraction (0.7)
        params["blend_opacity"] = val / 100.0 if val > 1 else val

    # pip_position
    if re.search(r'\b(top.?left|upper.?left)\b', text, re.I):
        params["pip_position"] = "top-left"
    elif re.search(r'\b(top.?right|upper.?right)\b', text, re.I):
        params["pip_position"] = "top-right"
    elif re.search(r'\b(bottom.?left|lower.?left)\b', text, re.I):
        params["pip_position"] = "bottom-left"
    else:
        params["pip_position"] = "bottom-right"  # default PiP position

    # fps

    m = re.search(r'(\d+)\s*fps', text, re.I)
    if m:
        params["fps"] = int(m.group(1))

    # youtube url
    m_url = re.search(
        r'(https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[A-Za-z0-9_-]+(?:[&?][^\s]*)?)',
        text
    )
    if m_url:
        params["url"] = m_url.group(1)

    # video quality, e.g. "720p" or "quality 1080" -- only meaningful
    # alongside a youtube url, so scope it there to avoid colliding
    # with duration/resolution parsing elsewhere
    if params["url"]:
        m_quality = re.search(
            r'\b(?:quality\s*(?:of|to)?\s*)?(144|240|360|480|720|1080|1440|2160)\s*p?\b',
            text, re.I
        )
        if m_quality:
            params["quality"] = int(m_quality.group(1))

        if re.search(r'\bdelete\s+(?:the\s+)?full\b', text, re.I):
            params["delete_full"] = True

    # extract all potential files
    # Match any non-whitespace filename ending with a supported extension
    all_files = re.findall(r'\b([^\s]+\.(?:mp4|mkv|avi|mov|webm|mp3|wav|png|jpg|jpeg))\b', text, re.I)

    # check if merging/swapping/replacing
    is_merge = any(w in text.lower() for w in ["merge", "combine", "join", "concatenate", "concat", "swap", "replace", "mix"])

    # find output file (as/into/output)
    m_out = re.search(r'\b(?:as|into|output)\s+([A-Za-z0-9_-]+\.(?:mp4|mkv|avi|mov|webm|mp3|wav|png|jpg|jpeg))\b', text, re.I)
    if m_out:
        params["output_file"] = m_out.group(1)
        params["input_files"] = [f for f in all_files if f.lower() != params["output_file"].lower()]
    elif is_merge:
        params["input_files"] = all_files
        params["output_file"] = "merged.mp4" if "merge" in text.lower() else None
    else:
        if all_files:
            if len(all_files) == 1:
                params["input_files"] = [all_files[0]]
            elif len(all_files) >= 2:
                params["output_file"] = all_files[-1]
                params["input_files"] = all_files[:-1]

    # legacy compatibility fallback
    if params["output_file"]:
        params["filename"] = params["output_file"]
    elif all_files:
        params["filename"] = all_files[-1]

    # resolution
    m = re.search(r'(\d+)\s*[xX×*]\s*(\d+)', text)

    if m:
        params["width"] = m.group(1)
        params["height"] = m.group(2)

        # Remove the matched resolution so later regexes don't see it
        text = text.replace(m.group(0), "")
    
    # start time
    m_start = re.search(r'\b(?:from|start|starting|ss|at)\s+(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?|\d{1,2}:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?)(?!\s*fps)\b', text, re.I)
    if m_start:
        params["start_time"] = m_start.group(1)

    # end time
    m_end = re.search(r'\b(?:to|end|ending)\s+(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?|\d{1,2}:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?)(?!\s*(?:fps|x|X|\.?\d|[A-Za-z0-9_-]+\.))\b', text, re.I)
    if m_end:
        params["end_time"] = m_end.group(1)

    # duration limit
    m_dur = re.search(r'\b(?:duration|for|t)\s+(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?|\d{1,2}:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?:sec|second|min|minute|hour)?\b', text, re.I)
    if m_dur:
        params["duration"] = m_dur.group(1)

    # transition style
    m_trans = re.search(r'\b(?:transition|using)\s+([a-zA-Z]+)(?!\.[a-zA-Z0-9]+)\b', text, re.I)
    if m_trans:
        params["transition"] = m_trans.group(1).lower()
    else:
        transitions = ["fade", "fadeblack", "fadewhite", "slideleft", "slideright", "slideup", "slidedown",
                       "wipeleft", "wiperight", "wipeup", "wipedown", "circleopen", "circleclose", "pixelize", "dissolve"]
        for t in transitions:
            if re.search(r'\b' + t + r'\b', text, re.I):
                params["transition"] = t
                break

    # speed_multiplier
    m_speed = re.search(r'\b(?:speed|tempo)\s*(?:up|down|to)?\s*(\d+(?:\.\d+)?)(?:x)?\b', text, re.I)
    if m_speed:
        params["speed_multiplier"] = float(m_speed.group(1))
    elif "speed up" in text.lower():
        params["speed_multiplier"] = 1.5
    elif "slow down" in text.lower():
        params["speed_multiplier"] = 0.8
        
    # volume_level
    m_vol = re.search(r'\bvolume\s*(?:to|of)?\s*(\d+(?:\.\d+)?)\b', text, re.I)
    if m_vol:
        params["volume_level"] = float(m_vol.group(1))
    elif "double volume" in text.lower():
        params["volume_level"] = 2.0
    elif "half volume" in text.lower():
        params["volume_level"] = 0.5
        
    # visual_type
    if "spectrogram" in text.lower():
        params["visual_type"] = "spectrogram"
    else:
        params["visual_type"] = "waveform"
        
    # fade_type
    if "fade out" in text.lower() or "fade-out" in text.lower():
        params["fade_type"] = "out"
    else:
        params["fade_type"] = "in"
        
    # fade_duration
    m_fade = re.search(r'\bfade\s*(?:in|out)?\s*(?:of|for|duration)?\s*(\d+(?:\.\d+)?)\s*(?:sec|second)?\b', text, re.I)
    if m_fade:
        params["fade_duration"] = float(m_fade.group(1))

    return params


# --- Tool implementations ---



def search_documents(query):

    query_embedding = model.encode([query])

    distances, indices = index.search(
        np.array(query_embedding).astype("float32"),
        1
    )

    best_chunk = chunks[indices[0][0]]

    return best_chunk, distances[0][0]


# --- CLI Prompt Loop ---

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VibeVideo CLI Editor")
    parser.add_argument("--media-dir", type=str, default="sample_media", help="Directory to scan for media files (default: sample_media)")
    args = parser.parse_args()

    # Change to media directory if specified so outputs go there
    if args.media_dir != ".":
        if os.path.exists(args.media_dir):
            os.chdir(args.media_dir)
        else:
            print(f"Error: Media directory '{args.media_dir}' does not exist.")
            sys.exit(1)

    while True:
        media_files, file_mapping = scan_media_files()
        if media_files:
            print(f"\nAvailable files in {args.media_dir}:")
            for idx, f in enumerate(media_files, start=1):
                print(f"  [{idx}] {f}")
        
        query = input("\nCommand: ")

        if query.lower() in ["quit", "exit"]:
            break

        processed_query = preprocess_query(query, file_mapping)
        if processed_query != query:
            print(f"Translated: {processed_query}")

        chunk, distance = search_documents(processed_query)
        lines = chunk["text"].split("\n")
        
        capability = lines[0]

        print("\nCapability:")
        print(capability)

        params = parse_parameters(processed_query)
        print("\nParsed Parameters:")
        print(params)

        instruction = find_mcp_instruction(
            capability,
            params
        )
        print("\nMCP Instruction:")
        print(instruction)

        tool = resolve_tool(instruction)

        print("\nSelected Tool:")
        print(tool)

        try:
            execute_tool_instruction(tool, instruction)
        except Exception as e:
            print(f"\nError running '{capability}': {e}")

