"""
Small computed-value helpers usable inside multicommand step definitions
via {"source": "computed", "func": "<name>", "on": "..."}.

Add new helpers here and register them in HELPERS as multicommands need
more computed values (e.g. thirds, N-way splits, etc).
"""

import imageio_ffmpeg

from engines.ffmpeg_engine import get_video_duration

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()


def duration(path):
    d = get_video_duration(path, FFMPEG_PATH)
    if d is None:
        raise ValueError(f"Could not determine duration of '{path}'")
    return d


def midpoint(path):
    return round(duration(path) / 2.0, 2)


HELPERS = {
    "duration": duration,
    "midpoint": midpoint,
}