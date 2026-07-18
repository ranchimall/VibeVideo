"""
Small computed-value helpers usable inside multicommand step definitions
via {"source": "computed", "func": "<name>", "on": "..."}.

Add new helpers here and register them in HELPERS as multicommands need
more computed values (e.g. thirds, N-way splits, etc).
"""
import re
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

# A time value: HH:MM:SS(.ms), MM:SS(.ms), or plain seconds.
_TIME = r'\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?|\d+(?:\.\d+)?'

# "the end" / "end" / "the end of the video" all mean "end of file".
_END_WORD = r'(?:the\s+)?end(?:\s+of\s+(?:the\s+)?(?:video|file|clip))?'

_RANGE_PATTERN = re.compile(
    rf'\bfrom\s+({_TIME})\s+(?:to|until|till)\s+({_END_WORD}|{_TIME})\b',
    re.I,
)


def count_time_ranges(raw_query):
    """Count 'from X to Y' occurrences in the query without needing a
    reference video (unlike parse_time_ranges, this never has to resolve
    'the end' to an actual duration). Used to deterministically route
    multi-range clip requests, instead of relying solely on semantic
    (FAISS) matching to distinguish them from single-range multicommands
    like subtitle_and_clip -- see vibevideo.py's Tier 1 dispatch."""
    return len(_RANGE_PATTERN.findall(raw_query))


def parse_time_ranges(raw_query, video_path=None):
    """Find every 'from <start> to <end>' occurrence in the query text and
    return them as a list of {"start": ..., "end": ...} dicts, in the order
    they appear. <end> may be a literal time, or a phrase like 'the end' /
    'until the end of the video', which resolves to the source video's
    duration (requires video_path).

    Only pairs written as "from X to/until/till Y" are recognized -- this
    intentionally does not try to guess ranges from bare "X to Y" text
    elsewhere in the query, to avoid false positives.
    """
    ranges = []
    for m in _RANGE_PATTERN.finditer(raw_query):
        start = m.group(1)
        end_raw = m.group(2)

        if re.fullmatch(_END_WORD, end_raw, re.I):
            if video_path is None:
                raise ValueError(
                    "Cannot resolve 'to the end' without a reference video."
                )
            end = duration(video_path)
        else:
            end = end_raw

        ranges.append({"start": start, "end": end})

    return ranges


REPEAT_SOURCES = {
    "time_ranges": parse_time_ranges,
}