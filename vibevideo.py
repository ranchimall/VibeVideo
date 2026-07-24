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
from multicommand.multi_executor import execute_multicommand
from multicommand.multi_helpers import count_time_ranges

print("Python:", sys.executable)
print("CWD:", os.getcwd())

# Check if user has a GPU but is stuck on CPU-only PyTorch
HAS_GPU = False
try:
    import torch
    if not torch.cuda.is_available():
        try:
            result = subprocess.run(['nvidia-smi'], capture_output=True, text=True)
            if result.returncode == 0:
                print("\n⚠️  NVIDIA GPU detected but PyTorch is CPU-only!")
                print("   Run this to enable GPU acceleration:")
                print("   pip install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu126")
                print("   (Note: Only NVIDIA GPUs support CUDA acceleration on Windows)\n")
        except FileNotFoundError:
            pass
    else:
        HAS_GPU = True
        print(f"GPU: {torch.cuda.get_device_name(0)} (CUDA {torch.version.cuda})")
except ImportError:
    pass

# path to ffmpeg binary
ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
MULTICOMMAND_MAX_DISTANCE = 0.9
YOUTUBE_URL_PATTERN = r'(https?://(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)[A-Za-z0-9_-]+(?:[&?][^\s]*)?)'
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}

def scan_media_files(directory="."):
    """Scan current directory for media files and build working name mappings."""
    extensions = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".mp3", ".wav", ".ogg", ".png", ".jpg", ".jpeg"}
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
    query = re.sub(r'\b(file\d+|f\d+)\b(?!\s*\.(?:mp4|mkv|avi|mov|webm|mp3|wav|ogg|png|jpg|jpeg))', replace_func, query, flags=re.I)
    
    # Match pattern: \[\d+\] but not followed by dot and extension
    def replace_bracket(match):
        bracketed = match.group(0)
        return mapping.get(bracketed, match.group(0))
        
    query = re.sub(r'\[\d+\](?!\s*\.(?:mp4|mkv|avi|mov|webm|mp3|wav|ogg|png|jpg|jpeg))', replace_bracket, query)
    
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

multicommand_documents_folder = os.path.join(BASE_DIR, "multicommand_documents")
 
def build_faiss_index(folder):
    from pathlib import Path
    multi_chunks = []
    if os.path.isdir(folder):
        for file in Path(folder).glob("*.txt"):
            with open(file, "r", encoding="utf-8") as f:
                text = f.read()
 
            sections = text.split("$$$|||")
 
            for section in sections:
                section = section.strip()
                if section:
                    multi_chunks.append({
                        "filename": file.name,
                        "text": section
                    })
 
    if not multi_chunks:
        return multi_chunks, None
 
    multi_texts = [c["text"] for c in multi_chunks]
    multi_embeddings = model.encode(multi_texts)
    multi_dimension = multi_embeddings.shape[1]
    multi_idx = faiss.IndexFlatL2(multi_dimension)
    multi_idx.add(np.array(multi_embeddings).astype("float32"))
    return multi_chunks, multi_idx
 
multi_chunks, multi_index = build_faiss_index(multicommand_documents_folder)
if multi_index is not None:
    print(f"FAISS index ready (multicommands, {len(multi_chunks)} registered phrasing(s)).\n")
else:
    print("No multicommands registered yet (multicommand_documents/ is empty).\n")

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
        "layer_mode": "tile",     # tile | pip | blend | overlay
        "old_text": None,
        "new_text": None,
        "target_object": None,
    }

    # Object Replacement (e.g. "replace the car in video with emoji.png")
    m_obj = re.search(r'\b(?:remove|replace)\s+(?:the\s+)?([a-zA-Z0-9\s]+?)\s+(?:in\s+[^\s]+\s+)?(?:and\s+replace\s+)?(?:with|to)\s+([^\s]+)', text, re.I)
    if m_obj:
        params["target_object"] = m_obj.group(1).strip()
        # Note: the replacement file (group 2) will be parsed by all_files below

    # Text Replacement (e.g. "change X to Y" or "replace X with Y in video")
    # Matches: change theFLOblockchain to FLO Blockchain in video.mp4
    m_text = re.search(r'\b(?:change|replace)\s+[\'"]?(.+?)[\'"]?\s+(?:to|with)\s+[\'"]?(.+?)[\'"]?(?:\s+(?:in|on|for|from|as))', text, re.I)
    if m_text:
        params["old_text"] = m_text.group(1).strip()
        params["new_text"] = m_text.group(2).strip()
    # layer_mode: overlay | tile (default)
    if re.search(r'\b(overlay|full.?screen|on top|screen|vfx|pip|picture.in.picture|corner|inset|small|miniature|blend|ghost|mix|transparent|opacity|see.?through)\b', text, re.I):
        params["layer_mode"] = "overlay"
    else:
        params["layer_mode"] = "tile"



    # fps

    m = re.search(r'(\d+)\s*fps', text, re.I)
    if m:
        params["fps"] = int(m.group(1))

    # youtube url
    m_url = re.search(YOUTUBE_URL_PATTERN, text)
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
    all_files = re.findall(r'\b([^\s]+\.(?:mp4|mkv|avi|mov|webm|mp3|wav|ogg|png|jpg|jpeg))\b', text, re.I)

    # check if merging/swapping/replacing
    is_merge = any(w in text.lower() for w in ["merge", "combine", "join", "concatenate", "concat", "swap", "replace", "mix"])

    # find output file (as/into/output)
    m_out = re.search(r'\b(?:as|into|output)\s+([A-Za-z0-9_-]+\.(?:mp4|mkv|avi|mov|webm|mp3|wav|ogg|png|jpg|jpeg))\b', text, re.I)
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

    # Extract per-file overlay positions (e.g. "top right", "bottom left")
    params["layer_positions"] = ["full"] * len(params.get("input_files", []))
    if params.get("input_files") and len(params["input_files"]) > 1:
        for i, filename in enumerate(params["input_files"]):
            if i == 0: continue # base video is always full
            
            start_idx = text.lower().find(filename.lower()) + len(filename)
            end_idx = len(text)
            
            if i < len(params["input_files"]) - 1:
                next_file = params["input_files"][i+1].lower()
                next_idx = text.lower().find(next_file, start_idx)
                if next_idx != -1:
                    end_idx = next_idx
                    
            if params.get("output_file"):
                out_idx = text.lower().find(params["output_file"].lower(), start_idx)
                if out_idx != -1 and out_idx < end_idx:
                    end_idx = out_idx
                    
            chunk = text[start_idx:end_idx]
            
            if re.search(r'\b(top.?left|upper.?left)\b', chunk, re.I):
                params["layer_positions"][i] = "top-left"
            elif re.search(r'\b(top.?right|upper.?right)\b', chunk, re.I):
                params["layer_positions"][i] = "top-right"
            elif re.search(r'\b(bottom.?left|lower.?left)\b', chunk, re.I):
                params["layer_positions"][i] = "bottom-left"
            elif re.search(r'\b(bottom.?right|lower.?right)\b', chunk, re.I):
                params["layer_positions"][i] = "bottom-right"
            # Otherwise remains "full"

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

def search_multicommands(query):
    """Tier 1 lookup: embed the query and search the multicommand-only
    FAISS index. Returns (name, distance) or (None, None) if no
    multicommands are registered."""
    if multi_index is None:
        return None, None
 
    query_embedding = model.encode([query])
    distances, indices = multi_index.search(
        np.array(query_embedding).astype("float32"),
        1
    )
 
    best_chunk = multi_chunks[indices[0][0]]
    name = best_chunk["text"].split("\n")[0].strip()
    return name, distances[0][0]

def resolve_multicommand_input_files(query, media_files):
    """Figure out which video the multicommand should run on. Reuses the
    same filename parsing as single commands, then falls back to 'the
    one video in the working directory' if the query didn't name one."""
    params = parse_parameters(query)
    input_files = list(params["input_files"])
 
    if not input_files and params["output_file"]:
        # e.g. query only mentioned one filename and it got parsed as output
        input_files = [params["output_file"]]
 
    if not input_files:
        video_candidates = [f for f in media_files if os.path.splitext(f.lower())[1] in VIDEO_EXTS]
        if len(video_candidates) == 1:
            input_files = [video_candidates[0]]
 
    return input_files    


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

    MEDIA_DIR_LABEL = os.path.basename(os.path.normpath(args.media_dir))

    def display_path(path):
        """Show paths rooted at the media folder name (e.g.
        'sample_media/whisper_output/x.srt') instead of a bare filename,
        so it's unambiguous where a generated file actually landed."""
        if not path:
            return path
        if os.path.isabs(path):
            return path
        return (MEDIA_DIR_LABEL + "/" + path).replace("\\", "/")
    
    last_outputs = []

    while True:
        media_files, file_mapping = scan_media_files()
        if media_files:
            print(f"\nAvailable files in {args.media_dir}:")
            for idx, f in enumerate(media_files, start=1):
                print(f"  [{idx}] {f}")

        if last_outputs:
            print(f"\nNew outputs:")
            for out in last_outputs:
                print(f"  {display_path(out)}")
            last_outputs = []
        
        
        query = input("\nCommand: ")

        if query.lower() in ["quit", "exit"]:
            break

        processed_query = preprocess_query(query, file_mapping)
        if processed_query != query:
            print(f"Translated: {processed_query}")

        # --- Tier 0: deterministic override for multi-range clipping ---
        # "clip from A to B and from C to D" is ambiguous for a semantic
        # matcher (it looks a lot like "clip from A to B and caption it"),
        # so don't leave this to FAISS distance -- if the query names 2+
        # explicit "from X to Y" ranges, it can only mean multi_range_clip.
        has_youtube_url = bool(re.search(YOUTUBE_URL_PATTERN, processed_query, re.I))
        wants_audio_only = bool(re.search(r'\b(mp3|audio)\b', processed_query, re.I))
        wants_video = bool(re.search(r'\b(video|subtitle|caption|srt)\b', processed_query, re.I))

        n_ranges = count_time_ranges(processed_query)
        is_delete = bool(re.search(r'\b(delete|remove|cut out)\b', processed_query, re.I))

        if has_youtube_url and wants_audio_only and not wants_video:
            multi_name, multi_distance = "youtube_to_mp3", 0.0
            print(f"\n[Tier 0] Detected youtube URL + audio-only request; routing directly to '{multi_name}'")
        elif is_delete and n_ranges >= 1:
            multi_name, multi_distance = "delete_time_ranges", 0.0
            print(f"\n[Tier 0] Detected delete intent with {n_ranges} range(s); routing directly to '{multi_name}'")
        elif n_ranges >= 2:
            multi_name, multi_distance = "multi_range_clip", 0.0
            print(f"\n[Tier 0] Detected multiple time ranges; routing directly to '{multi_name}'")
        else:
            # --- Tier 1: check registered multicommands first ---
            multi_name, multi_distance = search_multicommands(processed_query)

        if multi_name is not None and multi_distance < MULTICOMMAND_MAX_DISTANCE:
            print(f"\n[Tier 1] Matched multicommand '{multi_name}' (distance={multi_distance:.3f})")
 
            input_files = resolve_multicommand_input_files(processed_query, media_files)
            # Not every multicommand needs a local video -- e.g. one that
            # starts by downloading from YouTube. So we don't hard-abort
            # here. If a step actually needs "original_input" and none was
            # found, execute_multicommand already raises a clear error for
            # that specific case (see _resolve_file_ref in multi_executor.py).
 
            try:
                outputs = execute_multicommand(multi_name, processed_query, input_files)
                last_outputs = [o for o in outputs if o]
            except Exception as e:
                print(f"\nError running multicommand '{multi_name}': {e}")    
            continue
 
        if multi_distance is not None:
            print(f"[Tier 1] No confident multicommand match (best='{multi_name}', distance={multi_distance:.3f}); falling back to single command.")    

        
        # --- Single-capability path (unchanged) ---
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
            result = execute_tool_instruction(tool, instruction, HAS_GPU)
            outputs = result if isinstance(result, list) else [result]
            last_outputs = [o for o in outputs if o]
        except Exception as e:
            print(f"\nError running '{capability}': {e}")