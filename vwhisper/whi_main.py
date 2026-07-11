"""
Whisper + Semantic Search Video Clipper
-----------------------------------------
Pipeline:
    video.mp4 -> FFmpeg extracts audio -> Whisper transcribes ->
    Sentence Transformer + FAISS index -> semantic search for query ->
    FFmpeg clips the matching timestamp range

Usage:
    python main.py --video input/video.mp4 --query "the part where he talks about Dogecoin's market cap"

Requirements (install first):
    pip install openai-whisper sentence-transformers faiss-cpu numpy --break-system-packages
    # FFmpeg must be installed and on PATH (apt install ffmpeg / brew install ffmpeg)
"""

import argparse
import json
import os
import subprocess
import sys

import numpy as np


# ---------- Step 1: Extract audio ----------
def extract_audio(video_path: str, audio_path: str, ffmpeg_path: str = "ffmpeg") -> None:
    print(f"[1/5] Extracting audio from {video_path} ...")
    cmd = [
        ffmpeg_path, "-y",
        "-i", video_path,
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        audio_path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print(result.stderr.decode())
        sys.exit("FFmpeg audio extraction failed.")
    print(f"      Saved audio to {audio_path}")


# ---------- Step 2: Transcribe with Whisper ----------
def transcribe(audio_path: str, model_size: str, cache_path: str, task: str = "transcribe", language: str = None) -> list:
    # Cache transcript so repeated tests on the same video don't re-run Whisper
    if os.path.exists(cache_path):
        print(f"[2/5] Found cached transcript at {cache_path}, loading it...")
        with open(cache_path, "r") as f:
            return json.load(f)["segments"]

    print(f"[2/5] Transcribing with Whisper ({model_size}, task={task}) ... this can take a while on first run")
    import whisper

    model = whisper.load_model(model_size)
    result = model.transcribe(audio_path, task=task, language=language, word_timestamps=True)

    with open(cache_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"      Transcribed {len(result['segments'])} segments. Cached to {cache_path}")
    return result["segments"]


# ---------- Step 3: Build embeddings + FAISS index ----------
def build_index(segments: list):
    print("[3/5] Building sentence embeddings + FAISS index ...")
    from sentence_transformers import SentenceTransformer
    import faiss

    model = SentenceTransformer("all-MiniLM-L6-v2")
    texts = [seg["text"].strip() for seg in segments]
    embeddings = model.encode(texts, show_progress_bar=False)
    embeddings = np.array(embeddings).astype("float32")

    index = faiss.IndexFlatL2(embeddings.shape[1])
    index.add(embeddings)

    print(f"      Indexed {len(texts)} segments")
    return model, index


# ---------- Step 4: Semantic search ----------
def search(query: str, embed_model, index, segments: list, top_k: int = 3):
    print(f"[4/5] Searching for: \"{query}\"")
    query_emb = embed_model.encode([query]).astype("float32")
    distances, indices = index.search(query_emb, top_k)

    results = []
    for rank, idx in enumerate(indices[0]):
        seg = segments[idx]
        results.append({
            "rank": rank + 1,
            "distance": float(distances[0][rank]),
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"].strip(),
        })

    print("      Top matches:")
    for r in results:
        print(f"        #{r['rank']} [{fmt_time(r['start'])}-{fmt_time(r['end'])}] "
              f"(dist={r['distance']:.3f}) {r['text']}")

    return results


def fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


# ---------- Alternative Step 4: Keyword search (finds ALL occurrences) ----------
def normalize(s: str) -> str:
    """Lowercase and strip everything except letters/numbers so 'Ranchi Mall'
    and 'ranchimall' match the same way regardless of how Whisper split words."""
    return "".join(ch for ch in s.lower() if ch.isalnum())


def flatten_words(segments: list) -> list:
    """Pull a flat list of {word, start, end} dicts out of Whisper's segments.
    Whisper's word_timestamps=True puts a 'words' list on each segment."""
    words = []
    for seg in segments:
        seg_words = seg.get("words")
        if seg_words:
            for w in seg_words:
                words.append({
                    "word": w["word"],
                    "start": w["start"],
                    "end": w["end"],
                })
        else:
            # Fallback if word-level timestamps aren't present for some reason
            words.append({"word": seg["text"], "start": seg["start"], "end": seg["end"]})
    return words


def find_all_occurrences(query: str, segments: list) -> list:
    """Find every occurrence of `query` (word or phrase) in the transcript,
    using normalized substring matching so minor Whisper spacing/punctuation
    differences don't cause misses. Returns one entry per occurrence with
    tight start/end timestamps."""
    words = flatten_words(segments)

    norm_query = normalize(query)
    if not norm_query:
        return []

    # Build a normalized version of each word, and a parallel array mapping
    # each character position back to the word index it came from.
    norm_words = [normalize(w["word"]) for w in words]
    char_to_word_idx = []
    full_norm = []
    for i, nw in enumerate(norm_words):
        full_norm.append(nw)
        char_to_word_idx.extend([i] * len(nw))
    full_norm_str = "".join(full_norm)

    matches = []
    search_start = 0
    while True:
        pos = full_norm_str.find(norm_query, search_start)
        if pos == -1:
            break
        end_pos = pos + len(norm_query) - 1
        start_word_idx = char_to_word_idx[pos]
        end_word_idx = char_to_word_idx[end_pos]

        matches.append({
            "start": words[start_word_idx]["start"],
            "end": words[end_word_idx]["end"],
            "text": " ".join(w["word"].strip() for w in words[start_word_idx:end_word_idx + 1]),
        })
        search_start = end_pos + 1

    return matches


def merge_close_matches(matches: list, gap_seconds: float = 2.0) -> list:
    """If the same phrase is matched twice within a couple seconds (e.g. due
    to overlapping word boundaries), merge them into one occurrence."""
    if not matches:
        return matches
    matches = sorted(matches, key=lambda m: m["start"])
    merged = [matches[0]]
    for m in matches[1:]:
        if m["start"] - merged[-1]["end"] <= gap_seconds:
            merged[-1]["end"] = max(merged[-1]["end"], m["end"])
            merged[-1]["text"] += " ... " + m["text"]
        else:
            merged.append(m)
    return merged  

def format_srt_time(seconds: float) -> str:
    ms = int((seconds - int(seconds)) * 1000)
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_txt(segments: list, output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(f"{fmt_time(seg['start'])}  {seg['text'].strip()}\n")
    print(f"      Saved plain text transcript to {output_path}")


def generate_srt(segments: list, output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            f.write(f"{i}\n")
            f.write(f"{format_srt_time(seg['start'])} --> {format_srt_time(seg['end'])}\n")
            f.write(f"{seg['text'].strip()}\n\n")
    print(f"      Saved SRT subtitles to {output_path}")

def escape_path_for_ffmpeg_filter(path: str) -> str:
    """FFmpeg's subtitles filter needs forward slashes and an escaped colon
    (Windows drive letters like C:\\ break the filter syntax otherwise)."""
    abs_path = os.path.abspath(path).replace("\\", "/")
    abs_path = abs_path.replace(":", "\\:")
    return abs_path


def burn_subtitles(video_path: str, srt_path: str, output_path: str, ffmpeg_path: str = "ffmpeg") -> None:
    print(f"Burning subtitles from {srt_path} onto {video_path} ...")
    safe_srt = escape_path_for_ffmpeg_filter(srt_path)
    cmd = [
        ffmpeg_path, "-y",
        "-i", video_path,
        "-vf", f"subtitles='{safe_srt}'",
        "-c:a", "copy",
        output_path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print(result.stderr.decode())
        sys.exit("FFmpeg subtitle burning failed.")
    print(f"      Saved captioned video to {output_path}")    




# ---------- Step 5: Clip the video ----------
def clip_video(video_path: str, start: float, end: float, output_path: str, padding: float = 0.5, ffmpeg_path: str = "ffmpeg") -> None:
    start_padded = max(0, start - padding)
    end_padded = end + padding
    print(f"[5/5] Clipping video from {fmt_time(start_padded)} to {fmt_time(end_padded)} ...")

    cmd = [
        ffmpeg_path, "-y",
        "-i", video_path,
        "-ss", str(start_padded),
        "-to", str(end_padded),
        "-c:v", "libx264",
        "-c:a", "aac",
        output_path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print(result.stderr.decode())
        sys.exit("FFmpeg clipping failed.")
    print(f"      Saved clip to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Whisper + semantic search video clipper")
    parser.add_argument("--video", required=True, help="Path to input video")
    parser.add_argument("--query", required=False, default=None,
                         help="For --mode semantic: a natural language description. "
                              "For --mode keyword: an exact word or phrase to find every occurrence of. "
                              "Not needed with --transcript-only.")
    parser.add_argument("--transcript-only", action="store_true",
                         help="Only generate .txt and .srt transcript files, skip search and clipping")                          
    parser.add_argument("--mode", choices=["semantic", "keyword", "burn"], default="keyword",
                         help="'keyword' finds ALL exact occurrences of a word/phrase (e.g. a name). "
                              "'semantic' finds the single best conceptual match (e.g. 'the part about pricing').")
    parser.add_argument("--model", default="turbo", help="Whisper model size (tiny/base/small/medium/large-v3/turbo)")
    parser.add_argument("--task", choices=["transcribe", "translate"], default="transcribe",
                         help="'transcribe' keeps the original spoken language. "
                              "'translate' always outputs English, regardless of input language.")
    parser.add_argument("--language", default=None,
                         help="Language spoken in the audio, e.g. 'hi' for Hindi. "
                              "Optional — Whisper auto-detects if not specified.")
    parser.add_argument("--top-k", type=int, default=3, help="[semantic mode] Number of candidate matches to show")
    parser.add_argument("--pick", type=int, default=1, help="[semantic mode] Which ranked result to clip (1 = best)")
    parser.add_argument("--outdir", default="output", help="Output directory")
    parser.add_argument("--context", type=float, default=60.0,
                         help="Seconds of context to include before AND after the keyword (default 60s = ~2 min clip)")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    video_name = os.path.splitext(os.path.basename(args.video))[0]
    audio_path = os.path.join(args.outdir, f"{video_name}_audio.wav")
    transcript_cache = os.path.join(args.outdir, f"{video_name}_{args.task}_{args.model}_transcript.json")

    extract_audio(args.video, audio_path)
    segments = transcribe(audio_path, args.model, transcript_cache, task=args.task, language=args.language)
    txt_path = os.path.join(args.outdir, f"{video_name}_{args.task}.txt")
    srt_path = os.path.join(args.outdir, f"{video_name}_{args.task}.srt")
    generate_txt(segments, txt_path)
    generate_srt(segments, srt_path)

    if args.transcript_only:
        print("\nDone. Transcript-only mode — skipping search and clipping.")
        return

    if not args.query and args.mode != "burn":
        sys.exit("Error: --query is required unless you pass --transcript-only or use --mode burn")

    if args.mode == "burn":
        captioned_path = os.path.join(args.outdir, f"{video_name}_{args.task}_captioned.mp4")
        burn_subtitles(args.video, srt_path, captioned_path)
        print("\nDone.")
        print(f"Captioned video: {captioned_path}")
        return    

    if args.mode == "keyword":
        print(f"[3/4] Searching transcript for every occurrence of: \"{args.query}\"")
        matches = find_all_occurrences(args.query, segments)
        matches = merge_close_matches(matches)

        if not matches:
            print(f"\nNo occurrences of \"{args.query}\" found in the transcript.")
            print("Tip: check the cached transcript JSON to see how Whisper actually spelled/split the word.")
            return

        print(f"      Found {len(matches)} occurrence(s):")
        for i, m in enumerate(matches):
            print(f"        #{i + 1} [{fmt_time(m['start'])}-{fmt_time(m['end'])}] {m['text']}")

        print(f"[4/4] Clipping all {len(matches)} occurrence(s) ...")
        clip_paths = []
        for i, m in enumerate(matches):
            clip_path = os.path.join(args.outdir, f"{video_name}_clip_{i + 1}.mp4")
            clip_video(args.video, m["start"], m["end"], clip_path, padding=args.context)
            clip_paths.append(clip_path)

        print("\nDone.")
        for i, (m, path) in enumerate(zip(matches, clip_paths)):
            print(f"  Clip {i + 1}: [{fmt_time(m['start'])}-{fmt_time(m['end'])}] -> {path}")

    else:  # semantic mode
        clip_path = os.path.join(args.outdir, f"{video_name}_clip.mp4")
        embed_model, index = build_index(segments)
        results = search(args.query, embed_model, index, segments, top_k=args.top_k)

        chosen = results[args.pick - 1]
        clip_video(args.video, chosen["start"], chosen["end"], clip_path)

        print("\nDone.")
        print(f"Matched text: \"{chosen['text']}\"")
        print(f"Clip saved to: {clip_path}")


if __name__ == "__main__":
    main()
