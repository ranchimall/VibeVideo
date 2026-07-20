"""
Download a public YouTube video (video + audio merged into one file)
using yt-dlp, with ffmpeg used to merge the streams. Optionally trim it
to a time range afterward.

The trim step always runs locally against the already-downloaded file
(fast: local disk seeking + stream copy, no network, no re-encoding) --
it only runs if you pass --start and/or --end. Without those, this just
downloads the full video, same as before.

Usage:
    python ytdl.py "https://www.youtube.com/watch?v=VIDEO_ID"
    python ytdl.py "https://youtu.be/VIDEO_ID" --output-dir downloads
    python ytdl.py "URL" --quality 720
    python ytdl.py "URL" --start 00:00 --end 23:57
    python ytdl.py "URL" --start 8:10 --end 27:10 --delete-full
"""

import argparse
import os
import subprocess
import sys

import re
import yt_dlp
import imageio_ffmpeg

def parse_timestamp(value):
    """Accepts "SS", "MM:SS", or "HH:MM:SS" and returns whole seconds."""
    parts = value.strip().split(":")
    if len(parts) > 3:
        raise argparse.ArgumentTypeError(f"invalid timestamp: {value!r}")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid timestamp: {value!r}")

    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def download_video(url, output_dir=".", quality=None):
    """Always downloads the full video. Trimming, if requested, is a
    separate local step (see trim_clip) -- this keeps the download fast
    (plain stream copy/merge, same as before) with no network-side
    trimming involved."""
    os.makedirs(output_dir, exist_ok=True)

    if quality:
        fmt = f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]"
    else:
        fmt = "bestvideo+bestaudio/best"

    options = {
        "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
        "format": fmt,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "progress_hooks": [_progress_hook],
        "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe(),
    }

    # Download the video and get the raw filename
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
    # Sanitize filename: replace spaces with underscores and remove any problematic characters
    base, ext = os.path.splitext(os.path.basename(filename))
    safe_base = re.sub(r"[\s]+", "_", base)
    safe_base = re.sub(r"[\\/:*?\"<>|]", "", safe_base)  # strip illegal FS chars
    safe_name = f"{safe_base}{ext}"
    safe_path = os.path.join(os.path.dirname(filename), safe_name)
    if safe_path != filename:
        os.replace(filename, safe_path)
    return safe_path


def _progress_hook(d):
    if d["status"] == "downloading":
        pct = d.get("_percent_str", "").strip()
        speed = d.get("_speed_str", "").strip()
        print(f"\r  downloading... {pct} at {speed}", end="", flush=True)
    elif d["status"] == "finished":
        print("\n  download finished, merging with ffmpeg...")


def trim_clip(input_path, output_path, start=None, end=None):
    """Fast local trim: -ss before -i for input seeking, -c copy for
    stream copy (no re-encoding). Since it's a stream copy, the start may
    snap to the nearest keyframe at or before the requested time
    (typically off by a second or two)."""
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg_path, "-y"]
    if start is not None:
        cmd += ["-ss", str(start)]
    cmd += ["-i", input_path]
    if end is not None:
        duration = end - (start or 0)
        cmd += ["-t", str(duration)]
    cmd += ["-c", "copy", output_path]

    subprocess.run(cmd, check=True)


def _default_clip_path(full_path):
    base, ext = os.path.splitext(full_path)
    return f"{base}_clip{ext}"


def main():
    parser = argparse.ArgumentParser(description="Download a public YouTube video, with optional local trim")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--output-dir", default=".", help="Folder to save the video in")
    parser.add_argument("--quality", type=int, default=None, help="Max height in pixels, e.g. 720 or 1080 (default: best available)")
    parser.add_argument("--start", type=parse_timestamp, default=None, help="Clip start time, e.g. 8:10 or 00:08:10 (triggers local trim)")
    parser.add_argument("--end", type=parse_timestamp, default=None, help="Clip end time, e.g. 27:10 or 00:27:10 (triggers local trim)")
    parser.add_argument("--output", default=None, help="Clip output filename (default: <video title>_clip.mp4)")
    parser.add_argument("--delete-full", action="store_true", help="Delete the full downloaded file after trimming, keeping only the clip")
    args = parser.parse_args()

    if args.start is not None and args.end is not None and args.start >= args.end:
        print("--start must be earlier than --end", file=sys.stderr)
        sys.exit(1)

    try:
        full_path = download_video(args.url, output_dir=args.output_dir, quality=args.quality)
    except yt_dlp.utils.DownloadError as e:
        print(f"\nDownload failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nSaved full video to: {full_path}")

    if args.start is None and args.end is None:
        return  # no trim requested -- plain download, done

    clip_path = args.output or _default_clip_path(full_path)
    print(f"Trimming to clip: {clip_path}")
    try:
        trim_clip(full_path, clip_path, start=args.start, end=args.end)
    except subprocess.CalledProcessError as e:
        print(f"\nTrim failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Saved clip to: {clip_path}")

    if args.delete_full:
        os.remove(full_path)
        print(f"Deleted full video: {full_path}")


if __name__ == "__main__":
    main()
