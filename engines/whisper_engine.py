"""
MCP engine wrapper around vwhisper/whi_main.py.

whi_main.py is loaded by explicit file path (importlib), NOT via a normal
`import`, and NOT placed on sys.path as a package. This is deliberate:
whi_main.py itself does `import whisper` (the pip 'openai-whisper' package)
inside transcribe(). If the vwhisper/ folder were ever imported as a
top-level package named "whisper" while the project root sits on sys.path
(which it does, for the engines/mcp imports to work), it would shadow the
real pip package and break transcription. Loading by file path sidesteps
that entirely.
"""

import os

import imageio_ffmpeg

from _whi_loader import load_whi_main

whi_main = load_whi_main()

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}
DEFAULT_MODEL = "base"


def _video_and_srt(input_files):
    video_path, srt_path = None, None
    for f in input_files:
        ext = os.path.splitext(f.lower())[1]
        if ext == ".srt":
            srt_path = f
        elif ext in VIDEO_EXTS:
            video_path = f
    return video_path, srt_path


def _transcribe_video(video_path, task, language, model_size, outdir="whisper_output"):
    """Shared step: extract audio -> whisper transcribe (cached) -> segments."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file '{video_path}' does not exist.")

    os.makedirs(outdir, exist_ok=True)
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    audio_path = os.path.join(outdir, f"{video_name}_audio.wav")
    transcript_cache = os.path.join(outdir, f"{video_name}_{task}_{model_size}_transcript.json")

    whi_main.extract_audio(video_path, audio_path, ffmpeg_path=FFMPEG_PATH)
    segments = whi_main.transcribe(audio_path, model_size, transcript_cache, task=task, language=language)
    return segments, outdir, video_name


def _generate_subtitles(inp, output_file):
    input_files = inp.get("input_files") or []
    if not input_files:
        raise ValueError("generate_subtitles requires an input video file.")
    video_path = input_files[0]

    language = inp.get("language")
    task = inp.get("task") or "transcribe"
    model_size = inp.get("model") or DEFAULT_MODEL

    segments, outdir, video_name = _transcribe_video(video_path, task, language, model_size)

    srt_path = output_file or os.path.join(outdir, f"{video_name}_{task}.srt")
    whi_main.generate_srt(segments, srt_path)
    return srt_path


def _burn_subtitles(inp, output_file):
    input_files = inp.get("input_files") or []
    video_path, srt_path = _video_and_srt(input_files)

    if not video_path or not srt_path:
        raise ValueError("burn_subtitles requires one video file and one .srt file in input_files.")
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file '{video_path}' does not exist.")
    if not os.path.exists(srt_path):
        raise FileNotFoundError(f"Subtitle file '{srt_path}' does not exist.")

    if not output_file:
        base, ext = os.path.splitext(video_path)
        output_file = f"{base}_captioned{ext}"

    whi_main.burn_subtitles(video_path, srt_path, output_file, ffmpeg_path=FFMPEG_PATH)
    return output_file


def _clip_by_keyword(inp, output_file):
    input_files = inp.get("input_files") or []
    if not input_files:
        raise ValueError("clip_by_keyword requires an input video file.")
    video_path = input_files[0]

    query = inp.get("search_query")
    if not query:
        raise ValueError("clip_by_keyword requires a search_query.")

    context = inp.get("context") or 5.0
    language = inp.get("language")
    model_size = inp.get("model") or DEFAULT_MODEL

    segments, outdir, video_name = _transcribe_video(video_path, "transcribe", language, model_size)

    matches = whi_main.find_all_occurrences(query, segments)
    matches = whi_main.merge_close_matches(matches)
    if not matches:
        raise RuntimeError(f"No occurrences of '{query}' found in the transcript.")

    m = matches[0]
    if not output_file:
        output_file = os.path.join(outdir, f"{video_name}_clip.mp4")
    whi_main.clip_video(video_path, m["start"], m["end"], output_file, padding=float(context), ffmpeg_path=FFMPEG_PATH)
    return output_file


def _clip_by_semantic(inp, output_file):
    input_files = inp.get("input_files") or []
    if not input_files:
        raise ValueError("clip_by_semantic requires an input video file.")
    video_path = input_files[0]

    query = inp.get("search_query")
    if not query:
        raise ValueError("clip_by_semantic requires a search_query.")

    pick = int(inp.get("pick") or 1)
    language = inp.get("language")
    model_size = inp.get("model") or DEFAULT_MODEL

    segments, outdir, video_name = _transcribe_video(video_path, "transcribe", language, model_size)

    embed_model, index = whi_main.build_index(segments)
    results = whi_main.search(query, embed_model, index, segments, top_k=max(pick, 3))
    chosen = results[pick - 1]

    if not output_file:
        output_file = os.path.join(outdir, f"{video_name}_clip.mp4")
    whi_main.clip_video(video_path, chosen["start"], chosen["end"], output_file, ffmpeg_path=FFMPEG_PATH)
    return output_file


def execute_whisper(implementation, instruction):
    inp = instruction.get("input", {})
    output_file = instruction.get("output", {}).get("output_file")

    if implementation == "generate_subtitles":
        return _generate_subtitles(inp, output_file)
    elif implementation == "burn_subtitles":
        return _burn_subtitles(inp, output_file)
    elif implementation == "clip_by_keyword":
        return _clip_by_keyword(inp, output_file)
    elif implementation == "clip_by_semantic":
        return _clip_by_semantic(inp, output_file)
    else:
        raise ValueError(f"Unknown whisper implementation: {implementation}")