import os

import yt_dlp

from engines.ytdl import (
    download_video,
    trim_clip,
    parse_timestamp,
    _default_clip_path,
)

YOUTUBE_IMPLEMENTATIONS = {
    "download_youtube",
}


def _to_seconds(value):
    """Normalize a start/end time coming from an MCP instruction into
    whole seconds. Accepts None, an int/float already in seconds, or a
    string like "8:10" / "00:08:10" / "23" (same formats ytdl.py's CLI
    --start/--end accept)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return parse_timestamp(str(value))


def execute_youtube(implementation, instruction):

    if implementation not in YOUTUBE_IMPLEMENTATIONS:
        raise ValueError(f"Unknown youtube implementation: {implementation}")

    inp = instruction["input"]

    url = inp.get("url")
    if not url:
        raise ValueError("download_youtube requires a 'url' input")

    quality = inp.get("quality")
    delete_full = bool(inp.get("delete_full") or False)

    start = _to_seconds(inp.get("start_time"))
    end = _to_seconds(inp.get("end_time"))

    if start is not None and end is not None and start >= end:
        raise ValueError("start_time must be earlier than end_time")

    output_file = instruction["output"]["output_file"]

    output_dir = os.path.dirname(output_file) if output_file else "."
    output_dir = output_dir or "."

    print(f"\nDownloading: {url}")

    try:
        full_path = download_video(url, output_dir=output_dir, quality=quality)
    except yt_dlp.utils.DownloadError as e:
        raise RuntimeError(f"download_failed: {e}") from e

    print(f"Saved full video to: {full_path}")

    if start is None and end is None:
        if output_file and os.path.abspath(output_file) != os.path.abspath(full_path):
            os.replace(full_path, output_file)
            print(f"Renamed to: {output_file}")
            return output_file
        return full_path

    clip_path = output_file or _default_clip_path(full_path)
    print(f"Trimming to clip: {clip_path}")

    try:
        trim_clip(full_path, clip_path, start=start, end=end)
    except Exception as e:
        raise RuntimeError(f"trim_failed: {e}") from e

    print(f"Saved clip to: {clip_path}")

    if delete_full:
        os.remove(full_path)
        print(f"Deleted full video: {full_path}")

    print("\nDone.")
    return clip_path