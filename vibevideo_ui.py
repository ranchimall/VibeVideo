import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import time
import re
import base64
import html
import queue
import threading
import pandas as pd
import gradio as gr
import contextlib
import io
import hashlib
import itertools
from typing import Optional

# Import vibevideo backend module
import vibevideo

# ============================================================================
# TABLE OF CONTENTS  —  read this first
# ----------------------------------------------------------------------------
# Every section below is marked with a banner containing a unique anchor tag
# in square brackets, e.g. [SEC:CONFIG]. Search the file for the exact tag
# (including brackets) to jump straight to it — that's the "clear section"
# to hand an AI assistant when only one part of the app needs to change.
#
# ARCHITECTURE — Tab 1 is two grids + one shared Preview box, nothing else:
#   Grid 1  Library Grid    [SEC:UI-AVAILABLE-LIST] / [SEC:LIBRARY-GRID]
#           Upload media and browse it as thumbnails. Click a tile to drop
#           it straight onto Grid 2 — there is no separate staging list.
#   Grid 2  Working Grid    [SEC:UI-GRID-ACTIONS]
#           Where every clip actually lives and gets arranged (row = track,
#           column = ordering position within that row — NOT a shared
#           cross-row time-slot; each row plays its own clips back-to-back,
#           in column order, independently of every other row). All the
#           editing controls that used to live
#           in a separate "Active List" panel — target clip dropdown, Trim/
#           Move/Copy/Remove/Undo, arrow-move, row shift — are supporting
#           controls folded directly into this one section. There is no
#           second grid or list standing between the Library Grid and this
#           one; a raw timeline/action-log table is still available for
#           debugging, but only as a collapsed accordion here, not a
#           separate top-level panel.
#   Preview One shared box  [SEC:UI-UNIFIED-PREVIEW]
#           Single video + status pair. Every preview action in the app
#           (clip, clip selection, row, row selection, grid, grid selection,
#           Custom Selection) writes into this same box instead of each
#           having its own player — see [SEC:PREVIEW-CLIP]/[SEC:PREVIEW-ROW]/
#           [SEC:PREVIEW-GRID]/[SEC:PREVIEW-CUSTOM] for the four backend
#           scopes that all feed it.
#
# BACKEND — pure data/logic, no Gradio components
#   [SEC:CONFIG]              Paths, folders, media-type constants
#   [SEC:ENGINE]               Action list core (fold/resolve/move/undo) — the
#                              non-destructive editing model everything else
#                              is built on. Touch this only for timeline/
#                              action-model changes, not UI or rendering.
#   [SEC:INGEST]                File upload, library scan, proxy generation
#   [SEC:LIST-RENDER]          Working Grid renderers — timeline table, action
#                              log table, and the Working Grid HTML itself
#                              (pure functions: action_list -> display data)
#   [SEC:LIBRARY-GRID]         Grid 1 (Library Grid) — thumbnail grid
#                              sorting, toggle-select, per-type thumbnails
#   [SEC:ACTION-HANDLERS]      Button handlers that append actions (trim, move,
#                              copy, remove, undo, add-to-grid, grid move/shift)
#   [SEC:RENDER-HELPERS]       Shared ffmpeg render/export helpers used by all
#                              four preview scopes below (cache, concat, etc.)
#   [SEC:PREVIEW-CLIP]         Single-clip preview + in-clip selection preview
#   [SEC:PREVIEW-ROW]          Row (track) preview, selection preview, export
#   [SEC:PREVIEW-GRID]         Full-grid composite preview, selection, export
#   [SEC:PREVIEW-CUSTOM]       Custom Selection — any combination of clips/
#                              rows/columns, sharing render_grid_composite()
#                              with Grid level so export replicates preview
#                              (all four scopes above write into the single
#                              Preview box — [SEC:UI-UNIFIED-PREVIEW])
#   [SEC:AI-ASSISTANT]         AI Command Assistant tab — free-text NLP core
#                              shared by both AI entry points (_run_ai_core)
#   [SEC:AI-CHESSBOARD]        Chessboard AI command — scope resolution
#                              (Clip/Row/Grid), query building, writing the
#                              AI result back onto the Working Grid
#   [SEC:STARTUP]               App startup / library scan trigger
#
# UI — everything inside `with gr.Blocks() as demo:` must stay in one
# Python scope (Gradio requirement), so this is organized as clearly
# bannered sub-sections instead of separate files:
#   [SEC:UI-AVAILABLE-LIST]    Tab 1 left column: upload + Grid 1 (Library
#                              Grid: Available List table + thumbnail grid)
#   [SEC:UI-CHESSBOARD-AI]     Tab 1 left column: AI Command (Chessboard) panel
#   [SEC:UI-UNIFIED-PREVIEW]   Tab 1: the one shared Preview box — every
#                              preview button in the app targets this
#   [SEC:UI-GRID-ACTIONS]      Tab 1 right column: Grid 2 (Working Grid) +
#                              its Actions — old Active List dropdown
#                              functions folded directly in as supporting
#                              controls, no separate section or grid
#   [SEC:UI-ROW-PREVIEW]       Tab 1: Row Preview / Export controls (renders
#                              into the shared Preview box above)
#   [SEC:UI-GRID-PREVIEW]      Tab 1: Grid Preview / Export controls (renders
#                              into the shared Preview box above)
#   [SEC:UI-CUSTOM-SELECTION]  Tab 1: Custom Selection Preview / Export
#                              controls (renders into the shared Preview box)
#   [SEC:UI-ASSISTANT-TAB]     Tab 2: AI Command Assistant tab
#
# WIRING — event handlers (.click/.change), grouped to mirror the UI
# sections above so a change to one feature only touches one wiring group:
#   [SEC:WIRING-STARTUP]       demo.load + file upload
#   [SEC:WIRING-AI-ASSISTANT]  Tab 2 AI Assistant button
#   [SEC:WIRING-LIBRARY-GRID]       Library Grid (click/sort) wiring
#   [SEC:WIRING-CHESSBOARD-ADD]     Add-to-Working-Grid button
#   [SEC:WIRING-CHESSBOARD-AI]      Chessboard AI command button
#   [SEC:WIRING-GRID-SELECTION]     Clicking cells/rows on the Working Grid
#   [SEC:WIRING-CLIP-ACTIONS]       Clip preview/selection, trim/move/copy/
#                                    remove/undo
#   [SEC:WIRING-GRID-MOVE]          Grid arrow-move buttons, row shift
#   [SEC:WIRING-ROW-PREVIEW]        Row Preview / Export wiring
#   [SEC:WIRING-GRID-PREVIEW]       Grid Preview / Export wiring
#   [SEC:WIRING-CUSTOM-SELECTION]   Custom Selection wiring
#
# Rule of thumb when making a change: find the anchor for the *behavior*
# you're changing (backend), then the matching UI anchor if a control needs
# to move/change, then the matching WIRING anchor if inputs/outputs need to
# change. Most fixes only touch one of these three.
# ============================================================================

# --------------------------------------------------------------------------
# [SEC:CONFIG] Paths / config
# --------------------------------------------------------------------------

# Set Gradio's library directory to be the VibeVideo project's sample_media folder
LIBRARY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_media")
PROXY_DIR = os.path.join(LIBRARY_DIR, "proxies")
RENDER_CACHE_DIR = os.path.join(tempfile.gettempdir(), "vibevideo_render_cache")
EXPORT_DIR = os.path.join(tempfile.gettempdir(), "vibevideo_exports")
THUMB_DIR = os.path.join(tempfile.gettempdir(), "vibevideo_thumbnails")

os.makedirs(LIBRARY_DIR, exist_ok=True)
os.makedirs(PROXY_DIR, exist_ok=True)
os.makedirs(RENDER_CACHE_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)
os.makedirs(THUMB_DIR, exist_ok=True)

PROXY_HEIGHT = 480  # transcode target for fast preview renders
PROXY_WIDTH = 854    # fixed canvas width for preview proxies
EXPORT_WIDTH = 1920   # fixed canvas for full-res export renders
EXPORT_HEIGHT = 1080

MEDIA_TYPE_EXTENSIONS = {
    "video": {".mp4", ".mkv", ".avi", ".mov", ".webm"},
    "audio": {".mp3", ".wav", ".aac", ".flac", ".m4a", ".ogg"},
    "image": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"},
    "subtitle": {".srt", ".vtt", ".ass", ".sub"},
}
DEFAULT_DURATION = {"video": 0.0, "audio": 0.0, "image": 3.0, "subtitle": 5.0}

# --------------------------------------------------------------------------
# [SEC:ENGINE] CORE TIMELINE ENGINE LOGIC (derived from vibevideo_core.py)
# --------------------------------------------------------------------------

_seq_counter = itertools.count(1)

def next_sequence() -> int:
    return next(_seq_counter)

def make_action(instance_id: str, action_type: str, params: dict) -> dict:
    seq = next_sequence()
    return {
        "actionId": f"a{seq:05d}",
        "sequence": seq,
        "instanceId": instance_id,
        "type": action_type,
        "params": params,
        "timestamp": time.time(),
    }

def fold(action_list: list[dict], up_to_sequence: Optional[int] = None) -> dict[str, dict]:
    instances: dict[str, dict] = {}
    ordered = sorted(action_list, key=lambda a: a["sequence"])
    if up_to_sequence is not None:
        ordered = [a for a in ordered if a["sequence"] <= up_to_sequence]

    for action in ordered:
        instance_id = action["instanceId"]
        a_type = action["type"]
        params = action["params"]

        if a_type == "ADD":
            instances[instance_id] = {
                "instanceId": instance_id,
                "sourceMediaId": params["sourceMediaId"],
                "mediaType": params.get("mediaType", "video"),
                "inPoint": params["inPoint"],
                "outPoint": params["outPoint"],
                "row": params["row"],
                "col": params.get("col", 0),
                "rowSeq": action["sequence"],
                "active": True,
            }
        elif a_type == "TRIM":
            if instance_id in instances:
                instances[instance_id]["inPoint"] = params["newIn"]
                instances[instance_id]["outPoint"] = params["newOut"]
        elif a_type == "MOVE":
            if instance_id in instances:
                instances[instance_id]["row"] = params["newRow"]
                if "newCol" in params:
                    instances[instance_id]["col"] = params["newCol"]
                instances[instance_id]["rowSeq"] = action["sequence"]
        elif a_type == "REPLACE":
            if instance_id in instances:
                instances[instance_id]["sourceMediaId"] = params["newSourceMediaId"]
        elif a_type == "COPY":
            source = instances.get(instance_id)
            if source:
                new_id = params["newInstanceId"]
                target_row = params.get("newRow", source["row"])
                target_col = params.get("newCol", source["col"])
                instances[new_id] = {
                    **source,
                    "instanceId": new_id,
                    "row": target_row,
                    "col": target_col,
                    "rowSeq": action["sequence"],
                    "active": True,
                }
        elif a_type == "REMOVE":
            if instance_id in instances:
                instances[instance_id]["active"] = False
        elif a_type == "ROW_SHIFT":
            continue
        elif a_type == "ROW_OVERLAY_SET":
            continue
        elif a_type == "ROW_ZINDEX_SET":
            continue
        elif a_type == "CLIP_OVERLAY_SET":
            continue
        else:
            raise ValueError(f"Unknown action type: {a_type}")

    return instances

def fold_row_offsets(action_list: list[dict], up_to_sequence: Optional[int] = None) -> dict[int, float]:
    offsets: dict[int, float] = {}
    ordered = sorted(action_list, key=lambda a: a["sequence"])
    if up_to_sequence is not None:
        ordered = [a for a in ordered if a["sequence"] <= up_to_sequence]

    for action in ordered:
        if action["type"] != "ROW_SHIFT":
            continue
        row = action["params"]["row"]
        delta = action["params"]["deltaSeconds"]
        offsets[row] = offsets.get(row, 0.0) + delta

    return offsets

DEFAULT_OVERLAY_SCALE = 0.4  # PIP width as a fraction of canvas width (was 0.5)
DEFAULT_ROW_CORNERS = ["top-right", "top-left", "bottom-left", "bottom-right", "center"]

def get_default_row_corner(row: int) -> str:
    """Cycle default overlay corner for rows:
    Row 1 -> top-right, Row 2 -> top-left, Row 3 -> bottom-left, Row 4 -> bottom-right, Row 5 -> center, etc.
    """
    try:
        r_int = int(row)
    except (ValueError, TypeError):
        r_int = 1
    idx = max(0, r_int - 1) % len(DEFAULT_ROW_CORNERS)
    return DEFAULT_ROW_CORNERS[idx]

OVERLAY_CORNERS = {
    "top-right": "W-w-10:{y}",
    "top-left": "10:{y}",
    "bottom-right": "W-w-10:H-h-{y}",
    "bottom-left": "10:H-h-{y}",
    "center": "(W-w)/2:(H-h)/2",
}
CLIP_OVERLAY_BADGES = {
    "top-left": "↖",
    "top-right": "↗",
    "bottom-left": "↙",
    "bottom-right": "↘",
    "center": "•",
    "full": "⛶",
}
FULL_OVERLAY_CORNER = "full"  # special corner: full-canvas alpha-composited overlay (PNG transparency, etc.), no scale/position

def fold_row_overlay(action_list: list[dict], up_to_sequence: Optional[int] = None) -> dict[int, dict]:
    """Per-row overlay settings (scale + corner) for rows that aren't the
    base (see fold_row_zindex for which row that is). Same append-only fold
    pattern as fold_row_offsets — a ROW_OVERLAY_SET action just overwrites
    the latest scale/corner for that row; earlier settings are still in the
    action list for history/undo but folding only keeps the most recent one
    per row. corner == FULL_OVERLAY_CORNER means: skip scale/position
    entirely and alpha-composite the row full-canvas (real PNG transparency
    preserved) — see render_segment(preserve_alpha=True).
    """
    overlay: dict[int, dict] = {}
    ordered = sorted(action_list, key=lambda a: a["sequence"])
    if up_to_sequence is not None:
        ordered = [a for a in ordered if a["sequence"] <= up_to_sequence]

    for action in ordered:
        if action["type"] != "ROW_OVERLAY_SET":
            continue
        row = action["params"]["row"]
        overlay[row] = {
            "scale": action["params"]["scale"],
            "corner": action["params"]["corner"],
        }

    return overlay

def set_row_overlay(action_list: list[dict], row: int, scale: float, corner: str) -> list[dict]:
    if corner != FULL_OVERLAY_CORNER and corner not in OVERLAY_CORNERS:
        raise ValueError(f"Unknown corner: {corner}")
    scale = max(0.1, min(1.0, float(scale)))
    new_actions = list(action_list)
    new_actions.append(make_action(f"row::{row}", "ROW_OVERLAY_SET", {
        "row": row, "scale": scale, "corner": corner,
    }))
    return new_actions

def fold_clip_overlay(action_list: list[dict], up_to_sequence: Optional[int] = None) -> dict[str, dict]:
    """Per-clip overlay settings (scale + corner) for clips in non-base rows.
    Allows individual items in the same row to appear at different positions
    (e.g. top-left, top-right, center, full) or inherit the row default.
    """
    clip_overlay: dict[str, dict] = {}
    ordered = sorted(action_list, key=lambda a: a["sequence"])
    if up_to_sequence is not None:
        ordered = [a for a in ordered if a["sequence"] <= up_to_sequence]

    for action in ordered:
        if action["type"] != "CLIP_OVERLAY_SET":
            continue
        inst_id = action["instanceId"]
        clip_overlay[inst_id] = {
            "scale": action["params"].get("scale"),
            "corner": action["params"].get("corner"),
            "mode": action["params"].get("mode", "custom"),
        }

    return clip_overlay

def set_clip_overlay(action_list: list[dict], instance_id: str, scale: float, corner: str) -> list[dict]:
    if corner != FULL_OVERLAY_CORNER and corner not in OVERLAY_CORNERS:
        raise ValueError(f"Unknown corner: {corner}")
    scale = max(0.1, min(1.0, float(scale)))
    new_actions = list(action_list)
    new_actions.append(make_action(instance_id, "CLIP_OVERLAY_SET", {
        "scale": scale, "corner": corner, "mode": "custom",
    }))
    return new_actions

def reset_clip_overlay(action_list: list[dict], instance_id: str) -> list[dict]:
    new_actions = list(action_list)
    new_actions.append(make_action(instance_id, "CLIP_OVERLAY_SET", {
        "scale": None, "corner": "inherit", "mode": "inherit",
    }))
    return new_actions

def fold_row_zindex(action_list: list[dict], up_to_sequence: Optional[int] = None) -> dict[int, float]:
    """Which visual row is the full-canvas base vs. an overlay is normally
    just 'lowest row number wins' — this makes that swappable. Lower zIndex
    = further toward the bottom of the stack (the lowest zIndex among
    active visual rows becomes the base); rows with no explicit zIndex
    default to their own row number, so behavior is unchanged until you
    actually set one.
    """
    z: dict[int, float] = {}
    ordered = sorted(action_list, key=lambda a: a["sequence"])
    if up_to_sequence is not None:
        ordered = [a for a in ordered if a["sequence"] <= up_to_sequence]

    for action in ordered:
        if action["type"] != "ROW_ZINDEX_SET":
            continue
        z[action["params"]["row"]] = action["params"]["zIndex"]

    return z

def set_row_zindex(action_list: list[dict], row: int, z_index: float) -> list[dict]:
    new_actions = list(action_list)
    new_actions.append(make_action(f"row::{row}", "ROW_ZINDEX_SET", {
        "row": row, "zIndex": float(z_index),
    }))
    return new_actions

def resolve_grid(action_list: list[dict]) -> tuple[dict[tuple[int, int], dict], dict[int, float]]:
    instances = fold(action_list)
    active = [i for i in instances.values() if i["active"]]
    grid: dict[tuple[int, int], dict] = {}
    for inst in active:
        grid[(inst["row"], inst["col"])] = inst
    row_offsets = fold_row_offsets(action_list)
    return grid, row_offsets

def resolve_timeline_multitrack(action_list: list[dict]) -> list[dict]:
    instances = fold(action_list)
    active = [i for i in instances.values() if i["active"]]
    row_offsets = fold_row_offsets(action_list)

    rows: dict[int, list[dict]] = {}
    for inst in active:
        rows.setdefault(inst["row"], []).append(inst)

    result = []
    for row, members in rows.items():
        members.sort(key=lambda i: i["col"])
        cursor = row_offsets.get(row, 0.0)
        for inst in members:
            duration = round(inst["outPoint"] - inst["inPoint"], 3)
            clip = dict(inst)
            clip["duration"] = duration
            clip["timelineStart"] = cursor
            clip["timelineEnd"] = cursor + duration
            clip["label"] = f"R{row}C{inst['col']}"
            result.append(clip)
            cursor += duration

    result.sort(key=lambda c: (c["row"], c["col"]))
    return result

def move_on_grid(action_list: list[dict], instance_id: str, direction: str) -> list[dict]:
    deltas = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}
    if direction not in deltas:
        raise ValueError(f"Unknown direction: {direction}")

    grid, _ = resolve_grid(action_list)
    current = next((inst for inst in grid.values() if inst["instanceId"] == instance_id), None)
    if current is None:
        return action_list

    dr, dc = deltas[direction]
    new_row, new_col = current["row"] + dr, current["col"] + dc
    if new_row < 0 or new_col < 0:
        return action_list

    new_actions = list(action_list)
    occupant = grid.get((new_row, new_col))

    new_actions.append(make_action(instance_id, "MOVE", {"newRow": new_row, "newCol": new_col}))
    if occupant is not None and occupant["instanceId"] != instance_id:
        new_actions.append(make_action(
            occupant["instanceId"], "MOVE",
            {"newRow": current["row"], "newCol": current["col"]},
        ))

    return new_actions

def shift_row(action_list: list[dict], row: int, delta_seconds: float) -> list[dict]:
    new_actions = list(action_list)
    new_actions.append(make_action(f"row::{row}", "ROW_SHIFT", {
        "row": row, "deltaSeconds": delta_seconds,
    }))
    return new_actions

def parse_selection_string(text: str) -> list[dict]:
    """Parses the shared point/band selection syntax used identically by the
    Clip, Row, and Grid Selection bars (and boxes) on the Chessboard tab:
    a comma-separated list of tokens, each either a single time in seconds
    (a "point", e.g. `22.3`) or a `start-end` span (a "band", e.g. `10-15`).
    Multiple points/bands can be combined freely, e.g. `10-15, 22.3, 40-45`.
    Same function, same rules, at every level — nothing level-specific here.
    """
    text = (text or "").strip()
    if not text:
        return []

    entries = []
    for raw_token in text.split(","):
        token = raw_token.strip()
        if not token:
            continue
        if "-" in token[1:]:
            # The band separator is always the first "-" at index >= 1 — this
            # also correctly skips a leading "-" that's a negative sign on
            # the start value (e.g. "-5-10") rather than the separator.
            idx = token.index("-", 1)
            start_str, end_str = token[:idx], token[idx + 1:]
            try:
                start, end = float(start_str), float(end_str)
            except ValueError:
                raise ValueError(f"Couldn't parse band '{token}' — expected 'start-end', e.g. '10-15'.")
            if end <= start:
                raise ValueError(f"Band '{token}' has end <= start.")
            entries.append({"type": "band", "start": start, "end": end})
        else:
            try:
                t = float(token)
            except ValueError:
                raise ValueError(f"Couldn't parse '{token}' as a time (seconds).")
            entries.append({"type": "point", "time": t})

    return entries

def format_selection(selections: list[dict]) -> str:
    parts = []
    for s in selections:
        if s["type"] == "point":
            parts.append(f'{s["time"]:.2f}s')
        else:
            parts.append(f'{s["start"]:.2f}s\u2013{s["end"]:.2f}s')
    return " | ".join(parts) if parts else "(no selection)"

def selections_to_ranges(selections: list[dict], point_padding: float = 0.5, clamp_end: Optional[float] = None) -> list[tuple[float, float]]:
    raw_ranges = []
    for s in selections:
        if s["type"] == "point":
            start = max(0.0, s["time"] - point_padding)
            end = s["time"] + point_padding
        else:
            start, end = s["start"], s["end"]
        if clamp_end is not None:
            start = min(start, clamp_end)
            end = min(end, clamp_end)
        if end > start:
            raw_ranges.append((start, end))

    if not raw_ranges:
        return []

    raw_ranges.sort()
    merged = [raw_ranges[0]]
    for start, end in raw_ranges[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    return merged

def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters

def assign_labels(active_instances: list[dict]) -> None:
    rows: dict[int, list[dict]] = {}
    for inst in active_instances:
        rows.setdefault(inst["row"], []).append(inst)

    for row, members in rows.items():
        members.sort(key=lambda i: i["rowSeq"])
        for col_index, inst in enumerate(members):
            inst["col"] = col_index
            if len(members) == 1:
                inst["label"] = str(row)
            else:
                inst["label"] = f"{row}{_column_letter(col_index)}"

def resolve_timeline(
    action_list: list[dict],
    range_start: Optional[float] = None,
    range_end: Optional[float] = None,
) -> list[dict]:
    instances = fold(action_list)
    active = [i for i in instances.values() if i["active"]]
    assign_labels(active)
    active.sort(key=lambda i: (i["row"], i["col"]))

    for i in active:
        i["duration"] = round(i["outPoint"] - i["inPoint"], 3)

    if range_start is None and range_end is None:
        return active

    result = []
    cursor = 0.0
    for inst in active:
        t_start = cursor
        t_end = cursor + inst["duration"]
        cursor = t_end

        overlaps = (
            (range_start is None or t_end > range_start)
            and (range_end is None or t_start < range_end)
        )
        if overlaps:
            clipped = dict(inst)
            clipped["timelineStart"] = t_start
            clipped["timelineEnd"] = t_end
            result.append(clipped)

    return result

def undo_last_action(action_list: list[dict], instance_id: Optional[str] = None) -> list[dict]:
    if not action_list:
        return action_list

    if instance_id is None:
        target = max(action_list, key=lambda a: a["sequence"])
    else:
        scoped = [a for a in action_list if a["instanceId"] == instance_id]
        if not scoped:
            return action_list
        target = max(scoped, key=lambda a: a["sequence"])

    return [a for a in action_list if a["actionId"] != target["actionId"]]

# --------------------------------------------------------------------------
# [SEC:INGEST] Media ingest and Library scanning helpers
# --------------------------------------------------------------------------

def infer_media_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    for mtype, exts in MEDIA_TYPE_EXTENSIONS.items():
        if ext in exts:
            return mtype
    return "video"

def get_duration(filepath: str) -> float:
    # First attempt to get precise stream duration for audio or video streams
    for stype in ("a:0", "v:0"):
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", stype,
                "-show_entries", "stream=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", filepath,
            ],
            capture_output=True, text=True,
        )
        val = result.stdout.strip()
        if val and val != "N/A":
            try:
                dur = float(val)
                if dur > 0:
                    return round(dur, 3)
            except ValueError:
                pass

    # Fallback to format duration
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", filepath,
        ],
        capture_output=True, text=True,
    )
    try:
        return round(float(result.stdout.strip()), 3)
    except ValueError:
        return 0.0

_active_proxy_jobs = set()
_active_proxy_lock = threading.Lock()

def get_clean_proxy_path(filename: str) -> str:
    h = hashlib.md5(filename.encode("utf-8")).hexdigest()[:12]
    return os.path.join(PROXY_DIR, f"proxy_{h}.mp4")

def make_proxy(filename: str, filepath: str) -> str:
    proxy_path = get_clean_proxy_path(filename)
    tmp_path = f"{proxy_path}.tmp"

    if os.path.exists(proxy_path) and os.path.getsize(proxy_path) > 0:
        return proxy_path  # Reuse existing completed proxy

    with _active_proxy_lock:
        if proxy_path in _active_proxy_jobs:
            return proxy_path
        _active_proxy_jobs.add(proxy_path)

    try:
        vf = (
            f"scale={PROXY_WIDTH}:{PROXY_HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={PROXY_WIDTH}:{PROXY_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,fps=30"
        )
        # Encode to tmp_path first so partial/mid-write files are never exposed
        res = subprocess.run(
            [
                "ffmpeg", "-y", "-i", filepath,
                "-vf", vf,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                "-af", "aresample=44100:async=1",
                "-f", "mp4",
                tmp_path,
            ],
            capture_output=True,
        )
        if res.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            os.replace(tmp_path, proxy_path)
        else:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            raise RuntimeError(f"Proxy generation failed for {filepath}")
    finally:
        with _active_proxy_lock:
            _active_proxy_jobs.discard(proxy_path)

    return proxy_path

def is_proxy_ready(media: dict) -> bool:
    if not media:
        return False
    if media.get("mediaType") != "video":
        return True

    filename = media.get("filename")
    if not filename:
        return False

    clean_path = get_clean_proxy_path(filename)
    tmp_path = f"{clean_path}.tmp"

    with _active_proxy_lock:
        if clean_path in _active_proxy_jobs:
            return False

    if os.path.exists(tmp_path):
        return False

    if os.path.exists(clean_path) and os.path.getsize(clean_path) > 0:
        media["proxyPath"] = clean_path
        return True

    return False

class ProxyManager:
    """Background worker thread that manages video proxy generation with a priority queue.
    - Priority 1: High priority (User selected / clicked media)
    - Priority 2: Low priority (Full library background scan)
    """
    def __init__(self):
        self.task_queue = queue.PriorityQueue()
        self.lock = threading.Lock()
        self.counter = itertools.count()
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

    def _worker(self):
        while True:
            try:
                priority, count, media = self.task_queue.get()
                if media and media.get("mediaType") == "video":
                    filename = media.get("filename")
                    filepath = media.get("filepath")
                    if not is_proxy_ready(media) and filepath and os.path.exists(filepath):
                        try:
                            p = make_proxy(filename, filepath)
                            media["proxyPath"] = p
                        except Exception as e:
                            print(f"[ProxyManager] Background proxy failed for {filename}: {e}")
                self.task_queue.task_done()
            except Exception as e:
                print(f"[ProxyManager] Worker error: {e}")

    def enqueue_background(self, media: dict):
        """Enqueue for background processing (Priority 2)."""
        if not media or media.get("mediaType") != "video":
            return
        if is_proxy_ready(media):
            return
        self.task_queue.put((2, next(self.counter), media))

    def enqueue_priority(self, media: dict):
        """Enqueue with high priority (Priority 1) for user-selected items."""
        if not media or media.get("mediaType") != "video":
            return
        if is_proxy_ready(media):
            return
        self.task_queue.put((1, next(self.counter), media))

proxy_manager = ProxyManager()

def get_thumbnail_path(media_id: str) -> str:
    return os.path.join(THUMB_DIR, f"thumb_{media_id}.jpg")

def make_thumbnail(media: dict):
    """Generate (or reuse a cached) small JPEG thumbnail for a library item.
    Video: grabs a frame ~10% into the clip (capped at 5s in). Image: a
    downscaled copy of the image itself. Audio/subtitle have no visual frame
    — the grid tile falls back to a plain color+icon tile for those.
    """
    media_type = media.get("mediaType")
    if media_type not in ("video", "image"):
        return None

    thumb_path = get_thumbnail_path(media["mediaId"])
    if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
        return thumb_path

    filepath = media.get("filepath")
    if not filepath or not os.path.exists(filepath):
        return None

    cmd = ["ffmpeg", "-y"]
    if media_type == "video":
        seek = max(0.1, min(media.get("duration", 1.0) * 0.1, 5.0))
        cmd += ["-ss", str(seek)]
    cmd += ["-i", filepath, "-frames:v", "1", "-vf", "scale=160:-1", "-q:v", "4", thumb_path]

    subprocess.run(cmd, capture_output=True)
    return thumb_path if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0 else None

def ensure_proxy(media: dict) -> Optional[str]:
    """Ensure a proxy exists for a video media item. Generates on-demand only when needed for grid/preview."""
    if not media or media.get("mediaType") != "video":
        return None

    if is_proxy_ready(media):
        return media.get("proxyPath")

    proxy_manager.enqueue_priority(media)
    return media.get("proxyPath")

def _resolve_upload_path(f) -> str:
    if hasattr(f, "name"):
        return f.name
    if isinstance(f, dict) and "name" in f:
        return f["name"]
    return str(f)

def ingest_files(files, available_list, default_image_duration=None):
    if not files:
        return available_list, render_available_df(available_list), ""

    errors = []
    added = 0
    image_duration = DEFAULT_DURATION["image"]
    if default_image_duration not in (None, ""):
        try:
            image_duration = max(0.1, float(default_image_duration))
        except (TypeError, ValueError):
            pass

    for f in files:
        try:
            src_path = _resolve_upload_path(f)
            original_name = os.path.basename(src_path)
            media_id = f"med_{uuid.uuid4().hex[:8]}"
            dest_path = os.path.join(LIBRARY_DIR, f"{media_id}_{original_name}")
            shutil.copy(src_path, dest_path)

            media_type = infer_media_type(original_name)

            if media_type in ("video", "audio"):
                duration = get_duration(dest_path)
                if duration <= 0:
                    duration = DEFAULT_DURATION.get(media_type, 3.0)
            elif media_type == "image":
                duration = image_duration
            else:
                duration = DEFAULT_DURATION.get(media_type, 3.0)

            clean_proxy = get_clean_proxy_path(original_name)
            proxy_path = clean_proxy if (media_type == "video" and os.path.exists(clean_proxy) and os.path.getsize(clean_proxy) > 0) else None

            media_entry = {
                "mediaId": media_id,
                "filename": original_name,
                "filepath": dest_path,
                "proxyPath": proxy_path,
                "duration": duration,
                "mediaType": media_type,
                "createdAt": time.time(),
            }
            # Fast thumbnail extraction (~0.05-0.1s)
            make_thumbnail(media_entry)

            # Enqueue to background proxy worker
            proxy_manager.enqueue_background(media_entry)

            available_list.append(media_entry)
            added += 1
        except Exception as e:
            errors.append(f"{getattr(f, 'name', f)}: {e}")

    status = f"Added {added} file(s)."
    if errors:
        status += " Failed: " + "; ".join(errors)

    return available_list, render_available_df(available_list), status

def scan_existing_files(available_list):
    """Scans sample_media/ library directory on startup or reload to ingest files."""
    if not os.path.exists(LIBRARY_DIR):
        return available_list

    ignore_names = {"proxies", "whisper_output", "__pycache__"}
    all_exts = set()
    for exts in MEDIA_TYPE_EXTENSIONS.values():
        all_exts.update(exts)

    for name in os.listdir(LIBRARY_DIR):
        if name in ignore_names:
            continue
        full_path = os.path.join(LIBRARY_DIR, name)
        if not os.path.isfile(full_path):
            continue

        # Check if already tracked in the library
        is_known = any(os.path.abspath(m["filepath"]) == os.path.abspath(full_path) for m in available_list)
        if is_known:
            continue

        ext = os.path.splitext(name.lower())[1]
        if ext not in all_exts:
            continue

        try:
            media_type = infer_media_type(name)
            if media_type in ("video", "audio"):
                duration = get_duration(full_path)
                if duration <= 0:
                    duration = DEFAULT_DURATION.get(media_type, 3.0)
            else:
                duration = DEFAULT_DURATION.get(media_type, 3.0)

            clean_proxy = get_clean_proxy_path(name)
            proxy_path = clean_proxy if (media_type == "video" and os.path.exists(clean_proxy) and os.path.getsize(clean_proxy) > 0) else None

            media_entry = {
                "mediaId": f"med_{uuid.uuid4().hex[:8]}",
                "filename": name,
                "filepath": full_path,
                "proxyPath": proxy_path,
                "duration": duration,
                "mediaType": media_type,
                "createdAt": os.path.getmtime(full_path),
            }
            # Fast thumbnail extraction (~0.05-0.1s)
            make_thumbnail(media_entry)

            # Enqueue to background proxy worker (Priority 2)
            proxy_manager.enqueue_background(media_entry)

            available_list.append(media_entry)
        except Exception as e:
            print(f"Failed to scan existing file {name}: {e}")

    return available_list

def render_available_df(available_list):
    return pd.DataFrame(
        [[m["mediaId"], m["filename"], m.get("mediaType", "video"), m["duration"]] for m in available_list],
        columns=["mediaId", "filename", "mediaType", "duration"],
    )

def render_mapping_df(available_list):
    rows = []
    for idx, m in enumerate(available_list, start=1):
        labels = f"file{idx}, f{idx}, [{idx}], {m['filename']}"
        rows.append([labels, m["filename"], m.get("mediaType", "video"), f"{m['duration']:.2f}s"])
    return pd.DataFrame(rows, columns=["Valid Names in Commands", "Actual Library File", "Type", "Duration"])

# --------------------------------------------------------------------------
# [SEC:LIBRARY-GRID] Media Library — thumbnail grid, sorting, toggle-select
# Everything about the visual grid browser for the media library (as an
# alternative to the plain Available List dataframe/dropdown, which are left
# fully intact). Matching UI: [SEC:UI-AVAILABLE-LIST]. Matching wiring:
# [SEC:WIRING-LIBRARY-GRID].
# --------------------------------------------------------------------------

def thumbnail_data_uri(media: dict):
    thumb_path = make_thumbnail(media)
    if not thumb_path:
        return None
    try:
        with open(thumb_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
    except OSError:
        return None

LIBRARY_SORT_KEYS = ["Date Created", "Name (A-Z)", "File Type"]
LIBRARY_SORT_DIRS = ["Descending", "Ascending"]

def sort_media_library(available_list, sort_key="Date Created", sort_dir="Descending"):
    items = list(available_list)
    reverse = (sort_dir != "Ascending")
    if sort_key == "Name (A-Z)":
        items.sort(key=lambda m: m["filename"].lower(), reverse=reverse)
    elif sort_key == "File Type":
        items.sort(key=lambda m: (m.get("mediaType", ""), m["filename"].lower()), reverse=reverse)
    else:  # "Date Created" — default: latest created first
        items.sort(key=lambda m: m.get("createdAt", 0), reverse=reverse)
    return items

def render_media_library_grid_html(available_list, selected_media_id=None, sort_key="Date Created", sort_dir="Descending", selected_media_ids=None):
    """Renders the Media Library thumbnail grid.

    `selected_media_id` is the single tile currently focused (drives the
    inline preview + Target file dropdown, unchanged from before).
    `selected_media_ids` is the broader set of media currently "selected" —
    i.e. still backing an active clip on the Working Grid via a Library Grid
    click (see `library_selected_media_ids()`). Any media in that set (plus
    the focused tile itself) is checkmarked AND sorted into a top block of
    the grid — that block wraps onto as many rows as it needs, with every
    non-selected tile placed after it.
    """
    items = sort_media_library(available_list, sort_key, sort_dir)

    selected_set = set(selected_media_ids or set())
    if selected_media_id:
        selected_set.add(selected_media_id)

    # Stable-partition: selected tiles first (keeping their relative sort
    # order), then everything else — this is what puts selected media into
    # a wrapping top block of the grid.
    if selected_set:
        items = (
            [m for m in items if m["mediaId"] in selected_set]
            + [m for m in items if m["mediaId"] not in selected_set]
        )

    legend = " &nbsp; ".join(
        f'<span class="vv-f-{t}">{MEDIA_TYPE_ICON[t]} {t}</span>'
        for t in MEDIA_TYPE_ICON if t != "subtitle"
    )

    if not items:
        return (
            f'<div style="margin-bottom:6px;font-size:12px;">{legend}</div>'
            '<div style="color:#888;font-size:13px;padding:12px;">No media in the library yet — upload files above.</div>'
        )

    tiles = []
    for m in items:
        media_type = m.get("mediaType", "video")
        color = MEDIA_TYPE_COLOR.get(media_type, "#666")
        icon = MEDIA_TYPE_ICON.get(media_type, "\u25a0")
        is_selected = m["mediaId"] in selected_set
        safe_name = html.escape(m["filename"])

        check = ""
        if is_selected:
            check = '<div class="vv-check">\u2713</div>'

        data_uri = thumbnail_data_uri(m) if media_type in ("video", "image") else None
        if data_uri:
            visual = f'<img src="{data_uri}" class="vv-tile-img" alt="{safe_name}" />'
        else:
            visual = (
                f'<div class="vv-tile-ph" style="background:{color}33;">{icon}</div>'
            )

        duration_label = f"{m['duration']:.1f}s" if media_type in ("video", "audio") else media_type

        tiles.append(
            f'<div class="vv-tile{" vv-sel" if is_selected else ""} vv-b-{media_type}" '
            f'data-vv-mid="{html.escape(str(m["mediaId"]))}" '
            f'title="Click to select/deselect: {safe_name}">'
            f'{check}{visual}'
            '<div class="vv-tile-meta">'
            f'<span class="vv-f-{media_type}">{icon}</span> {safe_name}'
            f'<div class="vv-tile-dur">{duration_label}</div>'
            '</div></div>'
        )

    VISIBLE = 4   # number of tiles always visible
    selected_note = f" Selected media are pinned to the top." if selected_set else ""
    header = (
        f'<div style="margin-bottom:6px;font-size:12px;">{legend}</div>'
        f'<div style="margin-bottom:4px;font-size:11px;color:#888;">{len(items)} file(s). '
        f'Click a tile to select it, click again to deselect.{selected_note}</div>'
    )

    if len(tiles) <= VISIBLE:
        # All tiles fit — no toggle needed
        return (
            '<div onclick="' + html.escape(_LIB_TILE_DELEGATE_JS, quote=True) + '">'
            + header
            + '<div class="vv-lib-grid">'
            + "".join(tiles)
            + "</div></div>"
        )

    # Use a timestamp-based unique ID so re-renders never clash
    uid = f"vv_lib_extra_{id(items)}"
    visible_html = "".join(tiles[:VISIBLE])
    extra_html   = "".join(tiles[VISIBLE:])
    remaining    = len(tiles) - VISIBLE

    toggle_btn = (
        f'<div style="text-align:center;margin:6px 0;">'
        f'<button id="{uid}_btn" onclick="'
        f'(function(){{var x=document.getElementById(\'{uid}\');'
        f'var b=document.getElementById(\'{uid}_btn\');'
        f'if(x.style.display===\'none\'){{x.style.display=\'\';b.textContent=\'Show less ▲\';}}'
        f'else{{x.style.display=\'none\';b.textContent=\'Show all {remaining} more ▼\';}}'
        f'}})()" '
        f'style="background:#2a2a2a;color:#ccc;border:1px solid #555;border-radius:4px;'
        f'padding:5px 16px;cursor:pointer;font-size:12px;">'
        f'Show all {remaining} more ▼'
        f'</button></div>'
    )

    return (
        '<div onclick="' + html.escape(_LIB_TILE_DELEGATE_JS, quote=True) + '">'
        + header
        + '<div class="vv-lib-grid">'
        + visible_html
        + "</div>"
        + toggle_btn
        + f'<div id="{uid}" style="display:none;">'
        + '<div class="vv-lib-grid">'
        + extra_html
        + "</div></div></div>"
    )

def toggle_library_selection(bridge_value, selected_media_id):
    """Tile clicked in the Media Library grid — select it, or deselect if it
    was already the selected tile (click again to toggle off)."""
    if not bridge_value:
        return selected_media_id
    media_id = bridge_value.split("|")[0]
    return None if media_id == selected_media_id else media_id

def preview_library_media(available_list, selected_media_id):
    """Preview mechanism for the Media Library grid — works uniformly for
    video, audio, and image library items by reusing render_segment() with
    a throwaway pseudo-instance spanning the whole file."""
    if not selected_media_id:
        return None, "Click a tile above to preview it."

    media = next((m for m in available_list if m["mediaId"] == selected_media_id), None)
    if not media:
        return None, "Selected file is no longer in the library."

    if media.get("mediaType") == "video" and not is_proxy_ready(media):
        proxy_manager.enqueue_priority(media)
        dur_val = media.get("duration", 0.0)
        dur_str = f"{dur_val:.2f}s" if dur_val else "0s"
        return None, f"Media is loading, please wait. Or, continue adding more media to the grid box. (Duration: {dur_str} | 00:00 loaded)"

    pseudo_instance = {
        "instanceId": f"libpreview_{selected_media_id}",
        "sourceMediaId": selected_media_id,
        "inPoint": 0.0,
        "outPoint": media["duration"],
    }
    try:
        path = render_segment(pseudo_instance, available_list, use_proxy=True)
    except Exception as e:
        return None, str(e)

    return path, f"{media['filename']} \u2014 {media.get('mediaType', 'video')}, {media['duration']:.2f}s."

def library_selected_media_ids(added_map, action_list):
    """MediaIds currently backing an *active* instance on the Working Grid
    via a Library Grid selection. Broader than the single-tile focus state
    (`library_selection_state`) — this is what the Library Grid uses to
    decide which tiles are checkmarked and pinned to the top block, so a
    tile stays marked "selected" even after a different tile is clicked.
    Falls back to skipping stale `added_map` entries (e.g. the clip was
    removed directly via the Working Grid's own Remove/Undo) so the Library
    Grid never shows a checkmark for something that's no longer there.
    """
    if not added_map or not action_list:
        return set()
    instances = fold(action_list)
    return {
        media_id
        for media_id, instance_id in added_map.items()
        if instances.get(instance_id, {}).get("active")
    }

def refresh_library_grid_only(available_list, selected_media_id, sort_key, sort_dir, added_map=None, action_list=None):
    """Grid + 'Target file' dropdown refresh only — used for side-effect
    refreshes (upload, AI run, Remove, Undo, startup) that must NOT hijack
    the one shared Preview screen with a stale Library tile selection the
    user isn't actively engaging with right now."""
    selected_ids = library_selected_media_ids(added_map, action_list)
    grid_html_val = render_media_library_grid_html(
        available_list, selected_media_id, sort_key, sort_dir, selected_media_ids=selected_ids,
    )

    choices = [f'{m["mediaId"]} | {m["filename"]}' for m in available_list]
    matched = next((c for c in choices if c.startswith(f"{selected_media_id} | ")), None) if selected_media_id else None
    dropdown_update = gr.Dropdown(choices=choices, value=matched)

    return grid_html_val, dropdown_update

def refresh_library_view(available_list, selected_media_id, sort_key, sort_dir, added_map=None, action_list=None):
    """Full refresh used by the deliberate Library-preview interactions
    (tile click, sort controls): re-renders the grid + dropdown (via
    refresh_library_grid_only), AND pushes the selected tile into the one
    shared Preview screen + the one shared Selection system, exactly like
    every other preview action in the app."""
    grid_html_val, dropdown_update = refresh_library_grid_only(
        available_list, selected_media_id, sort_key, sort_dir, added_map, action_list,
    )

    preview_path, preview_status = preview_library_media(available_list, selected_media_id)

    if selected_media_id and preview_path is not None:
        media = next((m for m in available_list if m["mediaId"] == selected_media_id), None)
        duration = media["duration"] if media else 0.0
        label = f"Library: {media['filename']}" if media else "Library preview"
        preview_target = {"kind": "library", "media_id": selected_media_id, "duration": duration, "label": label}
        sel_bar_html = render_selection_bar_html(duration, "unified_sel_bar", "unified_sel_box")
    else:
        preview_target = None
        sel_bar_html = render_selection_bar_html(0.1, "unified_sel_bar", "unified_sel_box")

    return grid_html_val, dropdown_update, preview_path, preview_status, preview_target, sel_bar_html

def fast_refresh_ui_on_library_click(available_list, selected_media_id, sort_key, sort_dir, added_map, action_list, instance_choice, row_number, custom_selected_ids):
    """Stage A of the decoupled library-click pipeline — runs in ~20 ms,
    no FFmpeg involved.

    Returns everything that needs to change in the UI *immediately* after a
    tile is clicked:
      • library_grid_html  — re-rendered with the new checkmark state
      • working_grid_html  — clip now visible on the Chessboard
      • media_dropdown     — updated file choices
      • unified_preview_status — instant 'Generating preview…' message
      • preview_target_state  — updated to the clicked media
      • unified_sel_bar_html  — selection bar for the new media

    The actual video preview (FFmpeg render) is intentionally left out so
    that library_grid_html is NOT an output of the slow Stage B call, which
    means Gradio will never dim/lock the Library panel while FFmpeg works.
    """
    grid_html_val, dropdown_update = refresh_library_grid_only(
        available_list, selected_media_id, sort_key, sort_dir, added_map, action_list,
    )

    working_html = refresh_working_grid(action_list, instance_choice, row_number, custom_selected_ids)

    if selected_media_id:
        media = next((m for m in available_list if m["mediaId"] == selected_media_id), None)
        if media:
            duration = media.get("duration", 0.0)
            filename = media.get("filename", "")
            label = f"Library: {filename}"
            preview_target = {"kind": "library", "media_id": selected_media_id, "duration": duration, "label": label}
            sel_bar_html = render_selection_bar_html(duration, "unified_sel_bar", "unified_sel_box")
            # Status tells the user the preview is queued/generating — updated
            # again by Stage B once the actual file is ready.
            status_msg = f"Generating preview for {filename}…"
        else:
            preview_target = None
            sel_bar_html = render_selection_bar_html(0.1, "unified_sel_bar", "unified_sel_box")
            status_msg = "Generating preview…"
    else:
        preview_target = None
        sel_bar_html = render_selection_bar_html(0.1, "unified_sel_bar", "unified_sel_box")
        status_msg = "Click a tile above to preview it."

    return grid_html_val, working_html, dropdown_update, status_msg, preview_target, sel_bar_html

def render_library_preview_video_only(available_list, selected_media_id):
    """Stage B of the decoupled library-click pipeline — runs FFmpeg
    asynchronously *after* Stage A has already un-dimmed the Library panel.

    Outputs ONLY unified_preview_video and unified_preview_status so that
    library_grid_html is never touched here and therefore never dimmed by
    Gradio while this heavy operation is running.

    Unlike the old app46 code where the entire chain blocked for 40+ seconds
    before Stage B ran (so the proxy was usually ready by then), in app47
    Stage B fires just ~20ms after the click — meaning the proxy is almost
    certainly not finished yet for large files.  If we returned immediately
    with "Media is loading…" the preview would stay blank forever because
    nothing ever retries Stage B.  Instead we poll here (in this background
    Gradio worker thread) until the ProxyManager finishes, then do the normal
    render_segment call.  The Library panel stays fully interactive throughout
    because library_grid_html is NOT in our outputs list.

    Polling ceiling: MAX_PROXY_WAIT_S (10 min).  For non-video media or media
    whose proxy is already ready the poll loop is skipped entirely.
    """
    if not selected_media_id:
        return None, "Click a tile above to preview it."

    media = next((m for m in available_list if m["mediaId"] == selected_media_id), None)
    if not media:
        return None, "Selected file is no longer in the library."

    # Poll until the proxy for this video is ready, then fall through to the
    # normal preview render.  Non-video media skip straight to preview_library_media.
    if media.get("mediaType") == "video" and not is_proxy_ready(media):
        MAX_PROXY_WAIT_S = 600   # 10-minute safety ceiling
        POLL_INTERVAL_S  = 2.0   # check every 2 s — low CPU, fast enough feedback
        proxy_manager.enqueue_priority(media)
        elapsed = 0.0
        dur_val = media.get("duration", 0.0)
        dur_str = f"{dur_val:.2f}s" if dur_val else "0s"
        while elapsed < MAX_PROXY_WAIT_S:
            time.sleep(POLL_INTERVAL_S)
            elapsed += POLL_INTERVAL_S
            if is_proxy_ready(media):
                break
        if not is_proxy_ready(media):
            return None, (
                f"Proxy generation timed out for {media.get('filename', '')} "
                f"({dur_str}). Try clicking the tile again."
            )

    # Proxy ready (or non-video) — run the actual FFmpeg segment render.
    preview_path, preview_status = preview_library_media(available_list, selected_media_id)
    return preview_path, preview_status

def sync_library_selection_to_grid(bridge_value, selected_media_id, target_row, target_col, available_list, action_list, added_map):
    """Fires whenever a Library Grid tile is clicked. Keeps the Working Grid
    in lockstep with the tile's checkmarked state so the transfer is
    frictionless in both directions:
      - Selecting a tile adds it to the Working Grid at the current Row/Col
        fields, exactly as if 'Add to Working Grid \u2192' had been clicked
        — unless it's already on the grid from an earlier selection, in
        which case nothing new is added (no duplicates from re-clicking).
      - Deselecting a tile (clicking it again) removes the instance that
        was auto-added for it from the Working Grid.
    `added_map` tracks {mediaId: instanceId} only for instances that came in
    this way, so manually-added copies (via the dropdown + 'Add to Working
    Grid \u2192', or Trim/Move/Copy/AI results) are never touched by this.

    Whether a click is a *select* or *deselect* is decided from `added_map`
    (is this media currently backing an active instance?), not from which
    tile last had click-focus — so clicking any checkmarked tile deselects
    it, even after a different tile has since been clicked and become the
    focused one (needed now that the Library Grid can checkmark more than
    one tile at once).
    """
    added_map = dict(added_map or {})

    if not bridge_value:
        return (
            selected_media_id, action_list,
            render_active_df(action_list), render_action_df(action_list),
            gr.Dropdown(choices=instance_choices(action_list)), added_map,
        )

    clicked_media_id = bridge_value.split("|")[0]

    clicked_media = next((m for m in available_list if m["mediaId"] == clicked_media_id), None)
    if clicked_media:
        proxy_manager.enqueue_priority(clicked_media)

    is_active = False
    if clicked_media_id in added_map:
        instances = fold(action_list)
        existing = instances.get(added_map[clicked_media_id])
        is_active = bool(existing and existing.get("active"))

    if is_active:
        # Deselecting this tile -> remove the instance that was auto-added for it.
        instance_id = added_map.pop(clicked_media_id)
        action_list = list(action_list)
        action_list.append(make_action(instance_id, "REMOVE", {}))
        new_selected = None if selected_media_id == clicked_media_id else selected_media_id
        return (
            new_selected, action_list,
            render_active_df(action_list), render_action_df(action_list),
            gr.Dropdown(choices=instance_choices(action_list), value=None), added_map,
        )

    # Not currently active (never added, or stale/removed elsewhere) -> drop
    # any stale entry and add it fresh.
    added_map.pop(clicked_media_id, None)

    media = next((m for m in available_list if m["mediaId"] == clicked_media_id), None)
    if not media:
        return (
            selected_media_id, action_list,
            render_active_df(action_list), render_action_df(action_list),
            gr.Dropdown(choices=instance_choices(action_list)), added_map,
        )

    media_choice = f'{media["mediaId"]} | {media["filename"]}'
    action_list, active_df_val, action_df_val, dropdown_update = add_to_active(
        media_choice, target_row, target_col, available_list, action_list,
    )
    # place_media_on_grid() appends exactly one ADD action as the newest
    # entry, so its instanceId is reliably the clip we just created — safer
    # than searching by sourceMediaId, which could match an older instance
    # of the same file added some other way (dropdown, Copy, AI result).
    if action_list:
        added_map[clicked_media_id] = action_list[-1]["instanceId"]

    return clicked_media_id, action_list, active_df_val, action_df_val, dropdown_update, added_map

# --------------------------------------------------------------------------
# [SEC:LIST-RENDER] Active List / Action List / Grid rendering helpers
# --------------------------------------------------------------------------

def render_active_df(action_list):
    timeline = resolve_timeline_multitrack(action_list)
    return pd.DataFrame(
        [
            [c["instanceId"], c["label"], c["sourceMediaId"], c["inPoint"], c["outPoint"], c["row"]]
            for c in timeline
        ],
        columns=["instanceId", "label", "sourceMediaId", "inPoint", "outPoint", "row"],
    )

def render_action_df(action_list):
    ordered = sorted(action_list, key=lambda a: a["sequence"])
    return pd.DataFrame(
        [
            [a["sequence"], a["type"], a["instanceId"], str(a["params"])]
            for a in ordered
        ],
        columns=["sequence", "type", "instanceId", "params"],
    )

def instance_choices(action_list):
    timeline = resolve_timeline_multitrack(action_list)
    return [f'{c["label"]} ({c["instanceId"]})' for c in timeline]

MEDIA_TYPE_ICON = {
    "video": "\U0001F3AC",     # clapper board
    "audio": "\U0001F3B5",     # music note
    "image": "\U0001F5BC",     # framed picture
    "subtitle": "\U0001F4AC",  # speech balloon
}
MEDIA_TYPE_COLOR = {
    "video": "#2d6cdf",
    "audio": "#2da65a",
    "image": "#c98a1c",
    "subtitle": "#8a3fd1",
}
GRID_ROWS = 6
GRID_COLS = 8

def _grid_bridge_js(elem_id: str, value_expr: str) -> str:
    return (
        "var el=document.querySelector("
        f"'#{elem_id} textarea, #{elem_id} input');"
        "if(el){"
        f"el.value={value_expr};"
        "el.dispatchEvent(new Event('input',{bubbles:true}));"
        "}"
    )

# [VV-PERF] Delegated click handlers. Instead of baking a full copy of the
# bridge-dispatch JS into every tile/header cell, each clickable element now
# just carries tiny data attributes and ONE handler per grid (on the grid's
# root <div>) routes every click to the right hidden bridge textbox.
_LIB_TILE_DELEGATE_JS = (
    "var t=event.target.closest('[data-vv-mid]');"
    "if(t){var el=document.querySelector('#library_click_bridge textarea,#library_click_bridge input');"
    "if(el){el.value=t.getAttribute('data-vv-mid')+'|'+Date.now();"
    "el.dispatchEvent(new Event('input',{bubbles:true}));}}"
)
_GRID_DELEGATE_JS = (
    "var t=event.target.closest('[data-vv-act]');"
    "if(t){var br={cell:'grid_click_bridge',celltoggle:'custom_cell_click_bridge',"
    "row:'row_click_bridge',rowtoggle:'custom_row_click_bridge',"
    "col:'custom_col_click_bridge',all:'custom_all_click_bridge'}[t.getAttribute('data-vv-act')];"
    "if(br){var el=document.querySelector('#'+br+' textarea,#'+br+' input');"
    "if(el){el.value=(t.getAttribute('data-vv-id')||'')+'|'+Date.now();"
    "el.dispatchEvent(new Event('input',{bubbles:true}));}}}"
)

def render_working_grid_html(action_list, selected_instance_id=None, selected_row=None, custom_selected_ids=None):
    """The Working Media Grid — the single chessboard view of the Active List,
    used everywhere in the app (it used to be split across three separate
    grid renders: the Active List mirror, the main Grid, and a dedicated
    Custom Selection grid). It carries two independent selection layers at
    once:
      - Single-select (click a clip's body, or a row label): drives Target
        clip instance for Trim/Move/Copy/Remove/Undo, the AI Clip scope, and
        the Row Preview / AI Row scope target — same as the old main Grid.
      - Multi-select (click the small +/\u2713 badge on a clip, or a row/column
        header's own toggle): builds the Custom Selection set used by Custom
        Selection Preview / Export — same as the old dedicated Custom
        Selection grid, just layered onto the same cells instead of a
        separate grid underneath.
    """
    grid, row_offsets = resolve_grid(action_list)
    custom_selected_ids = set(custom_selected_ids or [])

    used_rows = {r for (r, c) in grid.keys()}
    used_cols = {c for (r, c) in grid.keys()}
    max_row = max(used_rows | {0}, default=0)
    max_col = max(used_cols | {0}, default=0)
    n_rows = max(GRID_ROWS, max_row + 2)
    n_cols = max(GRID_COLS, max_col + 2)

    try:
        selected_row_int = int(selected_row) if selected_row not in (None, "") else None
    except (TypeError, ValueError):
        selected_row_int = None

    # Column headers — click toggles every clip in that column into/out of
    # the Custom Selection (previously only on the separate Custom grid).
    # Top-left corner: "select all" toggle — selects/deselects every clip on the grid.
    all_ids = {inst["instanceId"] for inst in grid.values()}
    all_selected = bool(all_ids) and all_ids.issubset(custom_selected_ids)
    all_toggle_mark = "\u2713" if all_selected else "+"
    all_toggle_icon = (
        f'<span class="vv-toggle{" vv-sel" if all_selected else ""}">'
        f'{all_toggle_mark}</span>'
    )
    col_header_cells = [
        '<td data-vv-act="all" data-vv-id="all" class="vv-corner" '
        'title="Select / deselect all clips on the grid">{}</td>'.format(all_toggle_icon)
    ]
    for c in range(n_cols):
        col_ids = {inst["instanceId"] for (r, cc), inst in grid.items() if cc == c}
        col_selected = bool(col_ids) and col_ids.issubset(custom_selected_ids)
        col_toggle_mark = "\u2713" if col_selected else "+"
        col_toggle_icon = (
            f'<span class="vv-toggle{" vv-sel" if col_selected else ""}">'
            f'{col_toggle_mark}</span>'
        )
        col_header_cells.append(
            f'<td data-vv-act="col" data-vv-id="{c}" class="vv-colh{" vv-sel" if col_selected else ""}" '
            f'title="Click to add/remove every clip in column {c} to/from the Custom Selection">'
            f'<div class="vv-colh-in">'
            f'{col_toggle_icon}C{c}</div></td>'
        )
    rows_html = ["<tr>" + "".join(col_header_cells) + "</tr>"]

    for r in range(n_rows):
        offset = row_offsets.get(r, 0.0)
        offset_badge = f'<span class="vv-offbadge"> ({offset:+.1f}s)</span>' if offset else ""
        row_is_selected = selected_row_int is not None and selected_row_int == r

        row_ids = {inst["instanceId"] for (rr, cc), inst in grid.items() if rr == r}
        row_custom_selected = bool(row_ids) and row_ids.issubset(custom_selected_ids)
        row_toggle_mark = "\u2713" if row_custom_selected else "+"

        cells_html = [
            f'<td class="vv-rowlab{" vv-rowsel" if row_is_selected else ""}">'
            f'<span class="vv-toggle{" vv-sel" if row_custom_selected else ""}" '
            f'data-vv-act="rowtoggle" data-vv-id="{r}" '
            f'title="Add/remove every clip in row {r} to/from the Custom Selection">{row_toggle_mark}</span>'
            f'<span class="vv-rowname" data-vv-act="row" data-vv-id="{r}" '
            f'title="Click to select row {r} (Row Preview / Row-scope AI command)">R{r}{offset_badge}</span>'
            '</td>'
        ]
        for c in range(n_cols):
            inst = grid.get((r, c))
            if inst is None:
                cells_html.append(
                    f'<td class="vv-cell{" vv-rs" if row_is_selected else ""}">\u00b7</td>'
                )
                continue
            mtype = inst.get("mediaType", "video")
            icon = MEDIA_TYPE_ICON.get(mtype, "\u25a0")
            is_selected = inst["instanceId"] == selected_instance_id
            is_custom_selected = inst["instanceId"] in custom_selected_ids
            inst_id = html.escape(str(inst["instanceId"]))
            badge_mark = "\u2713" if is_custom_selected else "+"
            badge_title = "Remove from Custom Selection" if is_custom_selected else "Add to Custom Selection"
            toggle_badge = (
                f'<span class="vv-badge{" vv-sel" if is_custom_selected else ""}" '
                f'data-vv-act="celltoggle" data-vv-id="{inst_id}" title="{badge_title}">{badge_mark}</span>'
            )
            row_ov_map = fold_row_overlay(action_list)
            clip_ov_map = fold_clip_overlay(action_list)
            clip_ov_info = clip_ov_map.get(inst["instanceId"], {})
            ov_badge = ""
            if r > 0:
                if clip_ov_info.get("mode") == "custom" and clip_ov_info.get("corner") and clip_ov_info.get("corner") != "inherit":
                    c_corner = clip_ov_info["corner"]
                    c_size = int(float(clip_ov_info.get("scale", DEFAULT_OVERLAY_SCALE)) * 100)
                elif row_ov_map.get(r, {}).get("corner"):
                    c_corner = row_ov_map[r]["corner"]
                    c_size = int(float(row_ov_map[r].get("scale", DEFAULT_OVERLAY_SCALE)) * 100)
                else:
                    c_corner = get_default_row_corner(r)
                    c_size = int(DEFAULT_OVERLAY_SCALE * 100)
                c_mark = CLIP_OVERLAY_BADGES.get(c_corner, "⛶")
                ov_badge = (
                    f'<span class="vv-ovbadge" '
                    f'title="Overlay position: {c_corner} ({c_size}%)">{c_mark}</span>'
                )
            cells_html.append(
                f'<td data-vv-act="cell" data-vv-id="{inst_id}" '
                f'class="vv-cell-filled vv-b-{mtype} vv-g-{mtype}'
                f'{" vv-cellsel" if is_selected else ""}'
                f'{" vv-cs" if is_custom_selected else (" vv-rs" if row_is_selected else "")}">'
                f'{toggle_badge}{ov_badge}{icon}<br/><span class="vv-cellpos">R{r}C{c}</span></td>'
            )
        rows_html.append("<tr>" + "".join(cells_html) + "</tr>")

    legend = " &nbsp; ".join(
        f'<span class="vv-f-{t}">{MEDIA_TYPE_ICON[t]} {t}</span>'
        for t in MEDIA_TYPE_ICON
    )
    custom_note = f" {len(custom_selected_ids)} clip(s) currently in the Custom Selection." if custom_selected_ids else ""

    return (
        '<div onclick="' + html.escape(_GRID_DELEGATE_JS, quote=True) + '">'
        '<div class="vv-wg-scroll">'
        f'<div class="vv-wg-legend">{legend}</div>'
        '<div class="vv-wg-note">'
        'Tap a clip to load it as the Target clip instance (Trim/Move/Copy/Remove/Undo, AI Clip scope) '
        'and preview it. Tap a row label (R0, R1, ...) to select that row (Row Preview, AI Row scope). '
        'Tap the small +/\u2713 badge on a clip, or a row (R\u2026) / column (C\u2026) header, to add/remove it '
        f'from the Custom Selection used below.{custom_note}'
        '</div>'
        '<table class="vv-wg-table">'
        + "".join(rows_html) +
        "</table></div></div>"
    )

def parse_instance_choice(choice: str) -> str:
    if not choice:
        return ""
    return choice.rsplit("(", 1)[-1].rstrip(")")

# --------------------------------------------------------------------------
# [SEC:ACTION-HANDLERS] Action handlers (buttons that append to the action list)
# --------------------------------------------------------------------------

def add_to_active(media_choice, target_row, target_col, available_list, action_list):
    if not media_choice:
        return action_list, render_active_df(action_list), render_action_df(action_list), gr.Dropdown()

    media_id = media_choice.split(" | ")[0]
    media = next((m for m in available_list if m["mediaId"] == media_id), None)
    if not media:
        return action_list, render_active_df(action_list), render_action_df(action_list), gr.Dropdown()

    action_list, _placed_row, _placed_col, instance_id = place_media_on_grid(media, target_row, target_col, action_list)

    choices = instance_choices(action_list)
    # Select newly added instance in the dropdown
    new_choice = next((c for c in choices if parse_instance_choice(c) == instance_id), None)

    return (
        action_list,
        render_active_df(action_list),
        render_action_df(action_list),
        gr.Dropdown(choices=choices, value=new_choice),
    )

def refresh_working_grid(action_list, instance_choice, row_number, custom_selected_ids):
    """Standard re-render of the Working Media Grid. Used after nearly every
    action (add/trim/move/copy/remove/undo/AI command/library selection/
    custom-selection toggle) so all three of its selection layers — single
    clip, selected row, Custom Selection set — always stay in sync."""
    return render_working_grid_html(
        action_list, parse_instance_choice(instance_choice), row_number, custom_selected_ids,
    )

def select_grid_cell(bridge_value, action_list):
    if not bridge_value:
        return gr.Dropdown()
    instance_id = bridge_value.split("|")[0]
    choices = instance_choices(action_list)
    matched = next((c for c in choices if parse_instance_choice(c) == instance_id), None)
    if not matched:
        return gr.Dropdown(choices=choices)
    return gr.Dropdown(choices=choices, value=matched)

def select_grid_row(bridge_value):
    """Row label clicked on the Working Media Grid — select that row (feeds
    Row Preview/Export and the Chessboard AI command's Row scope) and switch
    the AI scope to Row."""
    if not bridge_value:
        return gr.Number(), gr.Radio()
    try:
        row = int(bridge_value.split("|")[0])
    except (ValueError, IndexError):
        return gr.Number(), gr.Radio()
    return row, "Row"

def grid_move(instance_choice, direction, action_list):
    instance_id = parse_instance_choice(instance_choice)
    if not instance_id:
        return action_list, render_active_df(action_list), render_action_df(action_list)

    action_list = move_on_grid(action_list, instance_id, direction)
    return (
        action_list,
        render_active_df(action_list),
        render_action_df(action_list),
    )

def grid_shift_row(row, delta_seconds, action_list):
    if row in (None, "") or delta_seconds in (None, ""):
        return action_list, render_active_df(action_list), render_action_df(action_list)

    action_list = shift_row(action_list, int(row), float(delta_seconds))
    return (
        action_list,
        render_active_df(action_list),
        render_action_df(action_list),
    )

def grid_set_row_overlay(row, scale_percent, corner, action_list):
    if row in (None, "") or scale_percent in (None, ""):
        return action_list, render_active_df(action_list), render_action_df(action_list), "Enter a row and a size first."

    action_list = set_row_overlay(action_list, int(row), float(scale_percent) / 100.0, corner)
    if corner == FULL_OVERLAY_CORNER:
        msg = (
            f"Row {int(row)} set to full-canvas alpha overlay — its real transparency "
            f"(e.g. a PNG's transparent background) is preserved and composited over "
            f"whatever is beneath it. Only takes effect if this row isn't the base "
            f"(see Layer priority below)."
        )
    else:
        msg = (
            f"Row {int(row)} PIP overlay set: {int(scale_percent)}% width, {corner}. "
            f"Only takes effect if this row isn't the base (see Layer priority below)."
        )
    return (
        action_list,
        render_active_df(action_list),
        render_action_df(action_list),
        msg,
    )

def grid_set_row_zindex(row, z_index, action_list):
    if row in (None, "") or z_index in (None, ""):
        return action_list, render_active_df(action_list), render_action_df(action_list), "Enter a row and a layer priority first."

    action_list = set_row_zindex(action_list, int(row), float(z_index))
    return (
        action_list,
        render_active_df(action_list),
        render_action_df(action_list),
        f"Row {int(row)} layer priority set to {z_index}. Among visual (video/image) rows, "
        f"whichever has the LOWEST priority number becomes the full-canvas base; every other "
        f"visual row overlays on top of it. Ties fall back to row number.",
    )

def grid_set_clip_overlay(instance_choice, mode, scale_percent, corner, action_list):
    instance_id = parse_instance_choice(instance_choice)
    if not instance_id:
        return action_list, render_active_df(action_list), render_action_df(action_list), "Select a target clip instance first."

    if mode == "Inherit from Row":
        action_list = reset_clip_overlay(action_list, instance_id)
        return (
            action_list,
            render_active_df(action_list),
            render_action_df(action_list),
            f"Clip {instance_id} reset to inherit its row overlay settings.",
        )

    if scale_percent in (None, "") or corner in (None, ""):
        return action_list, render_active_df(action_list), render_action_df(action_list), "Enter size and corner/mode first."

    scale = float(scale_percent) / 100.0
    action_list = set_clip_overlay(action_list, instance_id, scale, corner)
    if corner == FULL_OVERLAY_CORNER:
        msg = f"Clip {instance_id} set to full-canvas alpha overlay (preserves transparency)."
    else:
        msg = f"Clip {instance_id} position set: {corner} at {int(scale_percent)}% width."

    return (
        action_list,
        render_active_df(action_list),
        render_action_df(action_list),
        msg,
    )

def grid_reset_clip_overlay(instance_choice, action_list):
    instance_id = parse_instance_choice(instance_choice)
    if not instance_id:
        return action_list, render_active_df(action_list), render_action_df(action_list), "Select a target clip instance first."

    action_list = reset_clip_overlay(action_list, instance_id)
    return (
        action_list,
        render_active_df(action_list),
        render_action_df(action_list),
        f"Clip {instance_id} reset to inherit its row overlay settings.",
    )

def get_clip_overlay_ui_values(instance_choice, action_list):
    instance_id = parse_instance_choice(instance_choice)
    if not instance_id:
        return gr.Dropdown(value="Inherit from Row"), gr.Dropdown(value="top-right"), gr.Slider(value=40)
    clip_overlay = fold_clip_overlay(action_list)
    setting = clip_overlay.get(instance_id, {})
    inst = fold(action_list).get(instance_id)
    row = inst.get("row", 1) if inst else 1
    default_corner = fold_row_overlay(action_list).get(row, {}).get("corner") or get_default_row_corner(row)
    default_scale_pct = int(float(fold_row_overlay(action_list).get(row, {}).get("scale", DEFAULT_OVERLAY_SCALE)) * 100)
    if setting.get("mode") == "custom" and setting.get("corner") and setting.get("corner") != "inherit":
        scale_pct = int(float(setting.get("scale", DEFAULT_OVERLAY_SCALE)) * 100)
        return gr.Dropdown(value="Custom Position"), gr.Dropdown(value=setting.get("corner", default_corner)), gr.Slider(value=scale_pct)
    else:
        return gr.Dropdown(value="Inherit from Row"), gr.Dropdown(value=default_corner), gr.Slider(value=default_scale_pct)

def apply_trim(instance_choice, new_in, new_out, action_list):
    instance_id = parse_instance_choice(instance_choice)
    if not instance_id:
        return action_list, render_active_df(action_list), render_action_df(action_list)

    action_list.append(make_action(instance_id, "TRIM", {
        "newIn": float(new_in), "newOut": float(new_out),
    }))
    return action_list, render_active_df(action_list), render_action_df(action_list)

def apply_move(instance_choice, new_row, action_list):
    instance_id = parse_instance_choice(instance_choice)
    if not instance_id or new_row in (None, ""):
        return action_list, render_active_df(action_list), render_action_df(action_list)

    action_list.append(make_action(instance_id, "MOVE", {
        "newRow": int(new_row),
    }))
    return action_list, render_active_df(action_list), render_action_df(action_list)

def apply_copy(instance_choice, new_row, action_list):
    instance_id = parse_instance_choice(instance_choice)
    if not instance_id:
        return action_list, render_active_df(action_list), render_action_df(action_list), gr.Dropdown()

    current = fold(action_list).get(instance_id)
    if not current:
        return action_list, render_active_df(action_list), render_action_df(action_list), gr.Dropdown()

    new_instance_id = f"clip_{uuid.uuid4().hex[:6]}"
    params = {"newInstanceId": new_instance_id}
    if new_row not in (None, ""):
        params["newRow"] = int(new_row)

    action_list.append(make_action(instance_id, "COPY", params))
    choices = instance_choices(action_list)
    new_choice = next((c for c in choices if parse_instance_choice(c) == new_instance_id), None)

    return (
        action_list,
        render_active_df(action_list),
        render_action_df(action_list),
        gr.Dropdown(choices=choices, value=new_choice),
    )

def apply_remove(instance_choice, action_list):
    instance_id = parse_instance_choice(instance_choice)
    if not instance_id:
        return action_list, render_active_df(action_list), render_action_df(action_list), gr.Dropdown()

    action_list.append(make_action(instance_id, "REMOVE", {}))

    return (
        action_list,
        render_active_df(action_list),
        render_action_df(action_list),
        gr.Dropdown(choices=instance_choices(action_list), value=None),
    )

def apply_undo(action_list):
    action_list = undo_last_action(action_list)
    return (
        action_list,
        render_active_df(action_list),
        render_action_df(action_list),
        gr.Dropdown(choices=instance_choices(action_list), value=None),
    )

# --------------------------------------------------------------------------
# [SEC:RENDER-HELPERS] Preview rendering — shared ffmpeg helpers
# Used by all three preview levels below (clip / row / grid). If you're
# changing how segments are rendered, cached, or concatenated for *every*
# preview level at once, this is the section to touch.
# --------------------------------------------------------------------------

RENDER_LOGIC_VERSION = "v8"  # bump whenever render_segment()'s ffmpeg command changes,
                              # so stale cached renders can never be silently served

class ProxyLoadingException(Exception):
    def __init__(self, filename, duration=0.0):
        self.filename = filename
        self.duration = duration
        dur_str = f"{duration:.2f}s" if duration else "0s"
        super().__init__(f"Media is loading, please wait. Or, continue adding more media to the grid box. (Duration: {dur_str} | 00:00 loaded)")

def render_segment(instance, available_list, use_proxy=True, preserve_alpha=False, overlay_setting=None) -> str:
    """Renders a single clip instance to standardized video format.
    When overlay_setting is provided (for overlay rows / non-base rows), the clip
    is scaled and positioned at its designated corner/mode over a full transparent
    canvas with yuva420p / qtrle, enabling per-item overlay positioning within
    the same row.
    """
    media = next((m for m in available_list if m["mediaId"] == instance["sourceMediaId"]), None)
    if not media:
        raise ValueError(f"Source media not found: {instance['sourceMediaId']}")

    if use_proxy and media.get("mediaType") == "video":
        if not is_proxy_ready(media):
            proxy_manager.enqueue_priority(media)
            raise ProxyLoadingException(media.get("filename"), media.get("duration", 0.0))
        source_path = media.get("proxyPath") or get_clean_proxy_path(media["filename"])
    else:
        source_path = media["filepath"]
    is_image = media.get("mediaType") == "image"
    is_audio = media.get("mediaType") == "audio"
    use_alpha = (preserve_alpha and (is_image or is_audio)) or bool(overlay_setting)

    ov_tag = "norm"
    if overlay_setting:
        c_name = overlay_setting.get("corner", "top-right")
        s_val = int(float(overlay_setting.get("scale", 0.5)) * 100)
        ov_tag = f"ov_{c_name}_{s_val}"

    ext = "mov" if use_alpha else "mp4"
    key = f"{instance['instanceId']}_{instance['inPoint']}_{instance['outPoint']}_{'proxy' if use_proxy else 'full'}_{'alpha' if use_alpha else 'flat'}_{ov_tag}_{RENDER_LOGIC_VERSION}.{ext}"
    cached_path = os.path.join(RENDER_CACHE_DIR, key)

    if os.path.exists(cached_path):
        return cached_path

    duration = max(0.1, float(instance["outPoint"]) - float(instance["inPoint"]))
    canvas_w, canvas_h = (PROXY_WIDTH, PROXY_HEIGHT) if use_proxy else (EXPORT_WIDTH, EXPORT_HEIGHT)

    if is_audio and use_alpha:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(instance["inPoint"]),
            "-to", str(instance["outPoint"]),
            "-i", source_path,
            "-f", "lavfi",
            "-i", f"color=c=black@0.0:s={canvas_w}x{canvas_h}:r=30,format=yuva420p",
            "-map", "1:v:0",
            "-map", "0:a:0",
            "-vf", "format=yuva420p",
            "-c:v", "qtrle",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-af", "aresample=44100:async=1",
            "-shortest",
            "-t", f"{duration:.3f}",
            cached_path,
        ]
    elif is_audio:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(instance["inPoint"]),
            "-to", str(instance["outPoint"]),
            "-i", source_path,
            "-f", "lavfi",
            "-i", f"color=c=black:s={canvas_w}x{canvas_h}:r=30",
            "-map", "1:v:0",
            "-map", "0:a:0",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-af", "aresample=44100:async=1",
            "-shortest",
            "-t", f"{duration:.3f}",
            cached_path,
        ]
    elif overlay_setting:
        corner = overlay_setting.get("corner", "top-right")
        scale = float(overlay_setting.get("scale", DEFAULT_OVERLAY_SCALE))
        if corner == FULL_OVERLAY_CORNER:
            vf = (
                f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease,"
                f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:color=black@0.0,"
                f"format=yuva420p,setsar=1,fps=30"
            )
        else:
            target_w = max(32, int(canvas_w * scale))
            if corner == "top-left":
                pad_pos = "10:10"
            elif corner == "bottom-right":
                pad_pos = "ow-iw-10:oh-ih-10"
            elif corner == "bottom-left":
                pad_pos = "10:oh-ih-10"
            elif corner == "center":
                pad_pos = "(ow-iw)/2:(oh-ih)/2"
            else:  # "top-right" default
                pad_pos = "ow-iw-10:10"
            vf = (
                f"scale={target_w}:-2:force_original_aspect_ratio=decrease,"
                f"pad={canvas_w}:{canvas_h}:{pad_pos}:color=black@0.0,"
                f"format=yuva420p,setsar=1,fps=30"
            )

        if is_image:
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-ss", str(instance["inPoint"]),
                "-to", str(instance["outPoint"]),
                "-i", source_path,
                "-f", "lavfi",
                "-t", f"{duration:.3f}",
                "-i", "anullsrc=r=44100:cl=stereo",
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-vf", vf,
                "-c:v", "qtrle",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                "-af", "aresample=44100:async=1",
                "-t", f"{duration:.3f}",
                cached_path,
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(instance["inPoint"]),
                "-to", str(instance["outPoint"]),
                "-i", source_path,
                "-f", "lavfi",
                "-t", f"{duration:.3f}",
                "-i", "anullsrc=r=44100:cl=stereo",
                "-vf", vf,
                "-c:v", "qtrle",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                "-af", "aresample=44100:async=1",
                "-shortest",
                "-t", f"{duration:.3f}",
                cached_path,
            ]
    elif is_image and use_alpha:
        # PNG (or other alpha-capable image) source, alpha preserved:
        # pad with a *transparent* border instead of opaque black, keep the
        # alpha channel through to a lossless alpha-capable codec (qtrle in
        # a .mov container — H.264/mp4 can't carry alpha).
        vf = (
            f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease,"
            f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:color=black@0.0,"
            f"format=yuva420p,setsar=1,fps=30"
        )
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-ss", str(instance["inPoint"]),
            "-to", str(instance["outPoint"]),
            "-i", source_path,
            "-f", "lavfi",
            "-t", f"{duration:.3f}",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-vf", vf,
            "-c:v", "qtrle",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-af", "aresample=44100:async=1",
            "-t", f"{duration:.3f}",
            cached_path,
        ]
    elif is_image:
        # Image source: loop image and supply silent audio stream so concat maintains matching layouts.
        vf = (
            f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease,"
            f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,fps=30"
        )
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-ss", str(instance["inPoint"]),
            "-to", str(instance["outPoint"]),
            "-i", source_path,
            "-f", "lavfi",
            "-t", f"{duration:.3f}",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-af", "aresample=44100:async=1",
            "-t", f"{duration:.3f}",
            cached_path,
        ]
    else:
        # Video source: scale/pad to canvas and supply anullsrc fallback if silent.
        # Explicit audio resampling guarantees uniform 44.1kHz stereo output.
        vf = (
            f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease,"
            f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,fps=30"
        )
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(instance["inPoint"]),
            "-to", str(instance["outPoint"]),
            "-i", source_path,
            "-f", "lavfi",
            "-t", f"{duration:.3f}",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-af", "aresample=44100:async=1",
            "-shortest",
            "-t", f"{duration:.3f}",
            cached_path,
        ]

    subprocess.run(cmd, capture_output=True)
    return cached_path

def concat_files(paths: list[str], output_path: str, reencode: bool = True, has_alpha: bool = False) -> str:
    if len(paths) == 1:
        shutil.copy(paths[0], output_path)
        return output_path

    concat_list_path = os.path.join(RENDER_CACHE_DIR, f"concat_{uuid.uuid4().hex[:8]}.txt")
    with open(concat_list_path, "w") as f:
        for p in paths:
            f.write(f"file '{p}'\n")

    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path]
    if reencode and has_alpha:
        cmd += [
            "-c:v", "qtrle",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-af", "aresample=44100:async=1",
        ]
    elif reencode:
        cmd += [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-af", "aresample=44100:async=1",
        ]
    else:
        cmd += ["-c", "copy"]
    cmd += [output_path]
    subprocess.run(cmd, capture_output=True)
    return output_path

def sanitize_filename(name: str, default: str) -> str:
    safe = "".join(c for c in (name or "") if c.isalnum() or c in "-_")
    return safe or default

def render_from_ranges(source_path: str, ranges: list[tuple[float, float]], reencode_concat: bool = True):
    if not ranges:
        return None

    segment_paths = []
    for i, (start, end) in enumerate(ranges):
        seg_path = os.path.join(RENDER_CACHE_DIR, f"sel_{uuid.uuid4().hex[:8]}_{i}.mp4")
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(start), "-to", str(end),
                "-i", source_path,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                "-af", "aresample=44100:async=1",
                seg_path,
            ],
            capture_output=True,
        )
        if os.path.exists(seg_path) and os.path.getsize(seg_path) > 0:
            segment_paths.append(seg_path)

    if not segment_paths:
        return None

    output_path = os.path.join(RENDER_CACHE_DIR, f"selection_{uuid.uuid4().hex[:8]}.mp4")
    concat_files(segment_paths, output_path, reencode=reencode_concat)
    return output_path

def get_clip_duration(action_list, instance_id):
    timeline = resolve_timeline_multitrack(action_list)
    inst = next((c for c in timeline if c["instanceId"] == instance_id), None)
    return inst["duration"] if inst else 0.0

def get_row_duration(action_list, row):
    clips = render_row_clips(action_list, row)
    return sum(c["duration"] for c in clips)

def get_grid_duration(action_list):
    timeline = resolve_timeline_multitrack(action_list)
    return max((c["timelineEnd"] for c in timeline), default=0.0)

# --------------------------------------------------------------------------
# [SEC:UNIFIED-PREVIEW] The ONE Preview screen / ONE Selection system / ONE
# Export button, multiplexing every previous preview surface: single clip,
# a clip's in-clip selection, a row, the whole grid, a Custom Selection of
# any clips/rows/columns, a Media Library tile, and an AI Command result.
#
# `preview_target_state` is the single source of truth for "what's on the
# shared Preview screen right now" — every action that used to render into
# its own preview widget now instead (a) renders into the one shared
# unified_preview_video/status, and (b) records enough here to let the one
# shared Selection box and the one shared Export button re-derive the exact
# same content on demand, at proxy quality (for Preview Selection) or full
# quality (for Export), without ever drifting from what's on screen.
#
# preview_target dict shape: {"kind", ...kind-specific params..., "duration", "label"}
#   kind == "clip":    {"instance_choice"}                         (Actions / Grid click)
#   kind == "row":     {"row"}                                     (Row Preview)
#   kind == "grid":    {}                                          (Grid Preview)
#   kind == "custom":  {"selected_ids"}                            (Custom Selection)
#   kind == "library": {"media_id"}                                (Media Library tile)
#   kind == "raw":     {"raw_path"}                                (AI Command result)
# --------------------------------------------------------------------------

def _unified_sel_bar(duration):
    return render_selection_bar_html(duration, "unified_sel_bar", "unified_sel_box")

def set_preview_target_clip(instance_choice, action_list):
    """Wires alongside every 'this clip is now on the Preview screen' action
    (Grid click, dropdown selection, Preview This Clip) so the shared
    Selection bar always matches the clip currently shown."""
    instance_id = parse_instance_choice(instance_choice)
    if not instance_id:
        return None, _unified_sel_bar(0.1)
    duration = get_clip_duration(action_list, instance_id)
    timeline = resolve_timeline_multitrack(action_list)
    inst = next((c for c in timeline if c["instanceId"] == instance_id), None)
    label = f"Clip {inst['label']}" if inst else "Clip selection"
    target = {"kind": "clip", "instance_choice": instance_choice, "duration": duration, "label": label}
    return target, _unified_sel_bar(duration)

def set_preview_target_row(row, action_list):
    if row in (None, ""):
        return None, _unified_sel_bar(0.1)
    row = int(row)
    duration = get_row_duration(action_list, row)
    target = {"kind": "row", "row": row, "duration": duration, "label": f"Row {row} selection"}
    return target, _unified_sel_bar(duration)

def set_preview_target_grid(action_list):
    duration = get_grid_duration(action_list)
    target = {"kind": "grid", "duration": duration, "label": "Grid selection"}
    return target, _unified_sel_bar(duration)

def set_preview_target_custom(action_list, selected_ids):
    timeline = resolve_timeline_multitrack(action_list)
    ids = list(selected_ids or [])
    duration = max((c["timelineEnd"] for c in timeline if c["instanceId"] in ids), default=0.0)
    target = {"kind": "custom", "selected_ids": ids, "duration": duration, "label": "Custom Selection"}
    return target, _unified_sel_bar(duration)

def set_preview_target_raw(path, label):
    """For preview content that isn't re-derivable from the timeline (an AI
    Command result) — the rendered file itself is recorded directly."""
    if not path:
        return None, _unified_sel_bar(0.1)
    try:
        duration = get_duration(path)
    except Exception:
        duration = 0.0
    target = {"kind": "raw", "raw_path": path, "duration": duration, "label": label}
    return target, _unified_sel_bar(duration)

def resolve_preview_target_path(preview_target, action_list, available_list, use_proxy):
    """Re-derives the actual media file for whatever's on the shared Preview
    screen, at proxy quality (Preview Selection) or full quality (Export) —
    the single place every kind of preview content funnels through, so
    Preview and Export can never show/produce different things."""
    if not preview_target or not preview_target.get("kind"):
        return None, "Nothing in the Preview screen yet — preview a clip, row, grid, selection, library file, or AI result first."

    kind = preview_target["kind"]

    if kind == "clip":
        instance_id = parse_instance_choice(preview_target.get("instance_choice"))
        if not instance_id:
            return None, "Select a clip instance first."
        timeline = resolve_timeline_multitrack(action_list)
        inst = next((c for c in timeline if c["instanceId"] == instance_id), None)
        if not inst:
            return None, "That clip instance is no longer active (was it removed?)."
        try:
            path = render_segment(inst, available_list, use_proxy=use_proxy)
        except Exception as e:
            return None, str(e)
        return path, f"Clip {inst['label']} — {inst['duration']}s (in {inst['inPoint']}s, out {inst['outPoint']}s)."

    if kind == "row":
        return render_row(action_list, available_list, preview_target["row"], use_proxy=use_proxy)

    if kind == "grid":
        return render_grid_composite(action_list, available_list, use_proxy=use_proxy)

    if kind == "custom":
        return render_grid_composite(action_list, available_list, use_proxy=use_proxy, instance_ids=preview_target.get("selected_ids"))

    if kind == "library":
        media = next((m for m in available_list if m["mediaId"] == preview_target.get("media_id")), None)
        if not media:
            return None, "Selected file is no longer in the library."
        pseudo_instance = {
            "instanceId": f"libpreview_{preview_target.get('media_id')}",
            "sourceMediaId": preview_target.get("media_id"),
            "inPoint": 0.0,
            "outPoint": media["duration"],
        }
        try:
            path = render_segment(pseudo_instance, available_list, use_proxy=use_proxy)
        except Exception as e:
            return None, str(e)
        return path, f"{media['filename']} — {media.get('mediaType', 'video')}, {media['duration']:.2f}s."

    if kind == "raw":
        path = preview_target.get("raw_path")
        if not path or not os.path.exists(path):
            return None, "That AI result file is no longer available."
        return path, preview_target.get("label", "AI Output")

    return None, "Unknown preview target."

def preview_unified_selection(selection_text, preview_target, action_list, available_list):
    """The ONE 'Preview Selection' action — works against whatever is
    currently on the shared Preview screen, no matter which of the six
    kinds put it there."""
    full_path, msg = resolve_preview_target_path(preview_target, action_list, available_list, use_proxy=True)
    if full_path is None:
        return None, msg
    duration = preview_target.get("duration", 0.0)
    label = preview_target.get("label", "Selection")
    return render_selection_within(full_path, duration, selection_text, label)

def export_unified_preview(selection_text, preview_target, action_list, available_list, export_name):
    """The ONE Export button — exports exactly what's on the shared Preview
    screen: the trimmed Selection sub-range if one is typed in, otherwise
    the full clip/row/grid/selection/library-file/AI-result, always at full
    (non-proxy) quality."""
    if not preview_target or not preview_target.get("kind"):
        return None, "Nothing in the Preview screen yet — preview a clip, row, grid, selection, library file, or AI result first."

    full_path, msg = resolve_preview_target_path(preview_target, action_list, available_list, use_proxy=False)
    if full_path is None:
        return None, msg

    has_selection = bool(selection_text and selection_text.strip())
    kind = preview_target["kind"]

    if has_selection:
        duration = preview_target.get("duration", 0.0)
        label = preview_target.get("label", "Selection")
        out_path, sel_msg = render_selection_within(full_path, duration, selection_text, label)
        if out_path is None:
            return None, sel_msg
        base_msg = sel_msg
    else:
        out_path = full_path
        base_msg = msg

    default_names = {
        "clip": "clip_export", "row": "row_export", "grid": "vibevideo_grid_export",
        "custom": "vibevideo_custom_export", "library": "library_export", "raw": "ai_output_export",
    }
    safe_name = sanitize_filename(export_name, default_names.get(kind, "vibevideo_export"))
    final_path = os.path.join(EXPORT_DIR, f"{safe_name}.mp4")

    if out_path != final_path:
        if kind == "raw" and not has_selection:
            # The full (untrimmed) AI-result file is a live Library asset,
            # not a disposable render — copy it out, don't remove it from
            # the Library by moving it.
            shutil.copy2(out_path, final_path)
        else:
            shutil.move(out_path, final_path)

    return final_path, base_msg + f" Saved as {os.path.basename(final_path)}."

def render_selection_bar_html(duration: float, bar_id: str, textbox_elem_id: str) -> str:
    duration = max(duration, 0.1)
    ticks = []
    n_ticks = 5
    for i in range(n_ticks + 1):
        t = duration * i / n_ticks
        pct = 100 * i / n_ticks
        ticks.append(f'<div style="position:absolute;left:{pct}%;top:100%;font-size:10px;color:#888;transform:translateX(-50%);">{t:.1f}s</div>')

    mousedown_js = (
        "var r=this.getBoundingClientRect();"
        "this.dataset.vvStart=Math.min(1,Math.max(0,(event.clientX-r.left)/r.width));"
    )
    mouseup_js = (
        "var r=this.getBoundingClientRect();"
        "var endFrac=Math.min(1,Math.max(0,(event.clientX-r.left)/r.width));"
        "var startFrac=this.dataset.vvStart!==undefined?parseFloat(this.dataset.vvStart):endFrac;"
        f"var startTime=startFrac*{duration};"
        f"var endTime=endFrac*{duration};"
        "var token;"
        f"if(Math.abs(endTime-startTime)<({duration}*0.01)){{"
        "token=startTime.toFixed(2);"
        "}else{"
        "var lo=Math.min(startTime,endTime).toFixed(2);"
        "var hi=Math.max(startTime,endTime).toFixed(2);"
        "token=lo+'-'+hi;"
        "}"
        f"var el=document.querySelector('#{textbox_elem_id} textarea, #{textbox_elem_id} input');"
        "if(el){"
        "el.value=el.value&&el.value.trim()?(el.value+', '+token):token;"
        "el.dispatchEvent(new Event('input',{bubbles:true}));"
        "}"
    )

    return f'''
<div style="margin:8px 0 24px 0;">
  <div id="{bar_id}" style="position:relative;width:100%;height:36px;background:#222;
       border:1px solid #555;cursor:crosshair;user-select:none;"
       onmousedown="{mousedown_js}"
       onmouseup="{mouseup_js}">
  </div>
  <div style="position:relative;height:14px;">{"".join(ticks)}</div>
</div>
'''

# --------------------------------------------------------------------------
# [SEC:PREVIEW-CLIP] Single-clip preview + in-clip selection preview
# Everything about the "Single Clip preview" and its Selection bar on the
# Chessboard tab lives here. Matching UI: [SEC:UI-GRID-ACTIONS]. Matching
# wiring: [SEC:WIRING-CLIP-ACTIONS].
# --------------------------------------------------------------------------

def preview_single_clip(instance_choice, action_list, available_list):
    instance_id = parse_instance_choice(instance_choice)
    if not instance_id:
        return None, "Select a clip instance first."

    timeline = resolve_timeline_multitrack(action_list)
    instance = next((c for c in timeline if c["instanceId"] == instance_id), None)
    if not instance:
        return None, "That clip instance is no longer active (was it removed?)."

    try:
        rendered_path = render_segment(instance, available_list, use_proxy=True)
    except Exception as e:
        return None, str(e)

    return rendered_path, f"Clip {instance['label']} — {instance['duration']}s (in {instance['inPoint']}s, out {instance['outPoint']}s)."

def render_selection_within(full_path, duration, selection_text, label):
    """Shared time-selection renderer behind the Clip, Row, and Grid
    Selection boxes: parses `selection_text` with parse_selection_string(),
    turns the points/bands into merged (start, end) ranges clamped to
    `duration`, and cuts those ranges out of `full_path`. One function for
    all three levels so they can never drift apart on parsing, clamping, or
    the messages shown back to the user — `label` is the only thing that
    varies (e.g. "Selection", "Row 2 selection", "Grid selection").
    """
    try:
        selections = parse_selection_string(selection_text)
    except ValueError as e:
        return None, str(e)

    ranges = selections_to_ranges(selections, clamp_end=duration)
    if not ranges:
        return None, "No valid selection to preview — enter a point (e.g. '5') or band (e.g. '2-6')."

    out_path = render_from_ranges(full_path, ranges)
    if out_path is None:
        return None, "Selection render failed."

    return out_path, f"{label}: {format_selection(selections)} \u2192 {len(ranges)} range(s) rendered."

# --------------------------------------------------------------------------
# [SEC:PREVIEW-ROW] Row (track) preview, selection preview, and export
# Everything about "Row Preview / Export" lives here. Matching UI:
# [SEC:UI-ROW-PREVIEW]. Matching wiring: [SEC:WIRING-ROW-PREVIEW].
# --------------------------------------------------------------------------

def render_row_clips(action_list, row, instance_ids=None):
    timeline = resolve_timeline_multitrack(action_list)
    clips = [c for c in timeline if c["row"] == row]
    if instance_ids is not None:
        clips = [c for c in clips if c["instanceId"] in instance_ids]
    clips.sort(key=lambda c: c["col"])
    return clips

def render_row(action_list, available_list, row, use_proxy=True, instance_ids=None, preserve_alpha=False, is_overlay_row=False):
    """Renders a row as a single clip: its clips play back-to-back, in
    column order, each running its own full length before the next one
    starts immediately (no waiting for other rows). When is_overlay_row is True,
    each clip applies its individual clip overlay position (falling back to the
    row overlay setting) on a transparent canvas, allowing multiple items in the
    same row to have different screen positions.
    """
    row_clips = render_row_clips(action_list, row, instance_ids=instance_ids)
    if not row_clips:
        return None, f"Row {row} is empty."

    present_types = {c["mediaType"] for c in row_clips}
    has_video = bool(present_types & {"video", "image"})
    media_type = "mixed" if len(present_types) > 1 else next(iter(present_types))
    use_alpha = (preserve_alpha or is_overlay_row) and has_video
    ext = "mov" if use_alpha else "mp4"

    row_overlay_map = fold_row_overlay(action_list)
    clip_overlay_map = fold_clip_overlay(action_list)
    row_ov = row_overlay_map.get(row, {})

    segments = []
    try:
        for clip in row_clips:
            ov_setting = None
            if is_overlay_row and has_video and clip.get("mediaType") in ("video", "image"):
                c_ov = clip_overlay_map.get(clip["instanceId"], {})
                if c_ov.get("mode") == "custom" and c_ov.get("corner") and c_ov.get("corner") != "inherit":
                    ov_setting = {"scale": c_ov.get("scale", DEFAULT_OVERLAY_SCALE), "corner": c_ov.get("corner")}
                elif row_ov.get("corner"):
                    ov_setting = {"scale": row_ov.get("scale", DEFAULT_OVERLAY_SCALE), "corner": row_ov.get("corner")}
                else:
                    ov_setting = {"scale": DEFAULT_OVERLAY_SCALE, "corner": get_default_row_corner(row)}

            seg_path = render_segment(clip, available_list, use_proxy=use_proxy, preserve_alpha=use_alpha, overlay_setting=ov_setting)
            segments.append(seg_path)
    except Exception as e:
        return None, str(e)

    if not segments:
        return None, f"Row {row} has nothing to render."

    out_dir = RENDER_CACHE_DIR if use_proxy else EXPORT_DIR
    out_path = os.path.join(out_dir, f"row{row}_{uuid.uuid4().hex[:8]}.{ext}")
    concat_files(segments, out_path, has_alpha=use_alpha)

    labels = ", ".join(c["label"] for c in row_clips)
    return out_path, f"Row {row} ({media_type}): {len(row_clips)} clip(s), sequential — {labels}."

def preview_row(row, action_list, available_list):
    if row in (None, ""):
        return None, "Enter a row number to preview."
    return render_row(action_list, available_list, int(row), use_proxy=True)

# --------------------------------------------------------------------------
# [SEC:PREVIEW-GRID] Full-grid composite: preview, selection, export
# Everything about "Grid Preview / Export (entire composite)" lives here —
# this is the only place that produces a permanent export file. Matching
# UI: [SEC:UI-GRID-PREVIEW]. Matching wiring: [SEC:WIRING-GRID-PREVIEW].
# --------------------------------------------------------------------------

def render_pad(duration: float, canvas_w: int, canvas_h: int, has_video: bool, output_path: str, has_alpha: bool = False):
    if duration <= 0:
        return None
    if has_video and has_alpha:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=black@0.0:s={canvas_w}x{canvas_h}:d={duration},format=yuva420p",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", str(duration),
            "-vf", "format=yuva420p",
            "-c:v", "qtrle",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-af", "aresample=44100:async=1",
            output_path,
        ]
    elif has_video:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s={canvas_w}x{canvas_h}:d={duration}",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-af", "aresample=44100:async=1",
            output_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", str(duration),
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-af", "aresample=44100:async=1",
            output_path,
        ]
    subprocess.run(cmd, capture_output=True)
    return output_path if os.path.exists(output_path) and os.path.getsize(output_path) > 0 else None

def align_row_to_master(action_list, available_list, row, row_offsets, use_proxy, canvas_w, canvas_h, has_video, instance_ids=None, preserve_alpha=False, is_overlay_row=False):
    row_path, _ = render_row(action_list, available_list, row, use_proxy=use_proxy, instance_ids=instance_ids, preserve_alpha=preserve_alpha, is_overlay_row=is_overlay_row)
    if row_path is None:
        return None

    offset = row_offsets.get(row, 0.0)
    if offset <= 0:
        return row_path

    use_alpha = preserve_alpha and has_video
    ext = "mov" if use_alpha else "mp4"
    pad_path = os.path.join(RENDER_CACHE_DIR, f"pad_row{row}_{uuid.uuid4().hex[:8]}.{ext}")
    pad_result = render_pad(offset, canvas_w, canvas_h, has_video, pad_path, has_alpha=use_alpha)
    if not pad_result:
        return row_path

    aligned_path = os.path.join(RENDER_CACHE_DIR, f"aligned_row{row}_{uuid.uuid4().hex[:8]}.{ext}")
    concat_files([pad_result, row_path], aligned_path, reencode=True, has_alpha=use_alpha)
    return aligned_path

def render_grid_composite(action_list, available_list, use_proxy=True, instance_ids=None):
    """Composite renderer shared by Grid Preview/Export AND Custom Selection
    Preview/Export. `instance_ids=None` composites every row (Grid level,
    unchanged behavior). Passing a set of instance IDs restricts the
    composite to just those clips — whichever rows they fall in still
    overlay (video/image) or mix (audio) exactly like Grid level, just with
    only the selected clips concatenated within each row. Preview and
    Export both call this exact function (use_proxy=True/False), so a
    custom selection's export is guaranteed to replicate its preview.
    """
    grid, row_offsets = resolve_grid(action_list)
    row_overlay = fold_row_overlay(action_list)
    row_zindex = fold_row_zindex(action_list)
    if instance_ids is not None:
        instance_ids = set(instance_ids)
        grid = {k: v for k, v in grid.items() if v["instanceId"] in instance_ids}
    if not grid:
        empty_msg = "Selection is empty — nothing to preview." if instance_ids is not None else "Grid is empty — nothing to preview."
        return None, empty_msg

    # A row can mix clip types (e.g. an audio clip in column 0 followed by
    # a video clip in column 1, same track) — classify by the SET of types
    # present in the row, not by whichever clip happens to be last written
    # into a scalar dict (that silently drops to whatever type "won",
    # e.g. audio, and made the composite step map only that row's audio
    # stream — dropping its video entirely). Any video/image content in the
    # row makes it a visual row; the row's per-clip audio (real or silent)
    # still comes along for free since aligned_visual rows also feed
    # audio_raw_indices below.
    row_types: dict[int, set] = {}
    for (r, c), inst in grid.items():
        row_types.setdefault(r, set()).add(inst["mediaType"])

    canvas_w, canvas_h = (PROXY_WIDTH, PROXY_HEIGHT) if use_proxy else (EXPORT_WIDTH, EXPORT_HEIGHT)

    # Stacking order: lowest zIndex wins the full-canvas base slot (defaults
    # to the row's own number, so nothing changes until you set one via
    # ROW_ZINDEX_SET / grid_set_row_zindex — the base is fully swappable).
    all_visual_rows = sorted(
        (r for r, types in row_types.items() if types & {"video", "image"}),
        key=lambda r: row_zindex.get(r, r),
    )
    audio_rows = sorted(r for r, types in row_types.items() if "audio" in types and not (types & {"video", "image"}))
    subtitle_rows = sorted(r for r, types in row_types.items() if types == {"subtitle"})

    base_row = all_visual_rows[0] if all_visual_rows else None
    remaining_rows = all_visual_rows[1:]

    notes = []
    if subtitle_rows:
        notes.append(f"Subtitle row(s) {subtitle_rows} not burned in yet — coming in a follow-up.")

    aligned_visual = []
    if base_row is not None:
        p = align_row_to_master(action_list, available_list, base_row, row_offsets, use_proxy, canvas_w, canvas_h, has_video=True, instance_ids=instance_ids, preserve_alpha=False, is_overlay_row=False)
        if p:
            aligned_visual.append((base_row, p))

    aligned_alpha = []
    for r in remaining_rows:
        p = align_row_to_master(action_list, available_list, r, row_offsets, use_proxy, canvas_w, canvas_h, has_video=True, instance_ids=instance_ids, preserve_alpha=True, is_overlay_row=True)
        if p:
            aligned_alpha.append((r, p))

    aligned_audio = []
    for r in audio_rows:
        p = align_row_to_master(action_list, available_list, r, row_offsets, use_proxy, canvas_w, canvas_h, has_video=False, instance_ids=instance_ids)
        if p:
            aligned_audio.append((r, p))

    # Calculate row durations and max timeline duration across all active rows
    row_durations = {}
    for r in list(all_visual_rows) + list(audio_rows):
        r_clips = render_row_clips(action_list, r, instance_ids=instance_ids)
        r_offset = row_offsets.get(r, 0.0)
        row_durations[r] = r_offset + sum(c["duration"] for c in r_clips)
    max_duration = max(row_durations.values(), default=0.0)

    if not aligned_visual and not aligned_audio and not aligned_alpha:
        return None, "Nothing renderable in the grid (only empty or subtitle-only rows)."

    out_dir = RENDER_CACHE_DIR if use_proxy else EXPORT_DIR
    output_path = os.path.join(out_dir, f"grid_{uuid.uuid4().hex[:8]}.mp4")

    inputs = []
    filter_parts = []
    input_idx = 0
    video_raw_indices = []
    audio_raw_indices = []

    for r, p in aligned_visual:
        inputs += ["-i", p]
        video_raw_indices.append(input_idx)
        audio_raw_indices.append(input_idx)
        input_idx += 1

    for r, p in aligned_audio:
        inputs += ["-i", p]
        # Audio row rendered segment has a black video canvas and audio track
        if not video_raw_indices:
            video_raw_indices.append(input_idx)
        audio_raw_indices.append(input_idx)
        input_idx += 1

    alpha_raw_indices = []
    for r, p in aligned_alpha:
        inputs += ["-i", p]
        alpha_raw_indices.append((input_idx, r))
        audio_raw_indices.append(input_idx)
        input_idx += 1

    video_map_arg = None
    if video_raw_indices:
        base_idx = video_raw_indices[0]
        if base_row is not None:
            base_dur = row_durations.get(base_row, 0.0)
        else:
            # No visual rows: the "base" video was promoted from the first
            # audio row's black canvas (see the aligned_audio loop above),
            # so its real duration is that row's duration — not 0. Using 0
            # here padded the composite to double length.
            base_dur = row_durations.get(aligned_audio[0][0], max_duration) if aligned_audio else max_duration
        pad_dur = max_duration - base_dur
        if pad_dur > 0.05:
            filter_parts.append(f"[{base_idx}:v]tpad=stop_mode=add:stop_duration={pad_dur:.3f}:color=black[base_padded]")
            current_ref = "[base_padded]"
            video_map_arg = "[base_padded]"
        else:
            current_ref = f"[{base_idx}:v]"
            video_map_arg = f"{base_idx}:v"

    if alpha_raw_indices:
        if video_raw_indices:
            remaining_alpha = alpha_raw_indices
        else:
            first_idx, _first_row = alpha_raw_indices[0]
            current_ref = f"[{first_idx}:v]"
            remaining_alpha = alpha_raw_indices[1:]
            video_map_arg = f"{first_idx}:v"
        for j, (a_idx, a_row) in enumerate(remaining_alpha, start=1):
            out_label = f"alphaout{j}"
            filter_parts.append(f"{current_ref}[{a_idx}:v]overlay=0:0:format=auto:eof_action=pass[{out_label}]")
            current_ref = f"[{out_label}]"
            video_map_arg = current_ref

    audio_map_arg = None
    if len(audio_raw_indices) == 1:
        audio_map_arg = f"{audio_raw_indices[0]}:a"
    elif len(audio_raw_indices) > 1:
        amix_inputs = "".join(f"[{idx}:a]" for idx in audio_raw_indices)
        filter_parts.append(
            f"{amix_inputs}amix=inputs={len(audio_raw_indices)}:duration=longest:dropout_transition=0,aresample=44100:async=1[aout]"
        )
        audio_map_arg = "[aout]"

    cmd = ["ffmpeg", "-y"] + inputs
    if filter_parts:
        cmd += ["-filter_complex", ";".join(filter_parts)]
    if video_map_arg:
        cmd += ["-map", video_map_arg]
    if audio_map_arg:
        cmd += ["-map", audio_map_arg]
    if video_map_arg:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]
    if audio_map_arg:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2"]
    cmd += [output_path]

    subprocess.run(cmd, capture_output=True)

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        return None, "Grid composite render failed — check ffmpeg is on PATH and all source media is valid."

    summary = f"Composited {len(aligned_visual)} visual row(s), {len(aligned_audio)} audio row(s)."
    if aligned_alpha:
        summary += f" +{len(aligned_alpha)} full-canvas alpha overlay row(s)."
    if instance_ids is not None:
        summary = (
            f"Composited custom selection: {len(grid)} clip(s) across "
            f"{len(aligned_visual)} visual row(s) + {len(aligned_audio)} audio row(s)"
            + (f" + {len(aligned_alpha)} alpha overlay row(s)" if aligned_alpha else "") + "."
        )
    if notes:
        summary += " " + " ".join(notes)
    return output_path, summary

def preview_grid(action_list, available_list):
    return render_grid_composite(action_list, available_list, use_proxy=True)

def render_selected_clips_sequential(action_list, available_list, instance_ids, use_proxy=False):
    """Concatenates exactly the checked clips, in (row, col) order, into one
    linear video — used by the "Selected Clips" AI scope.

    Unlike render_grid_composite() (which treats different rows as z-index
    layers / PiP overlays — Grid semantics), this ignores row/track grouping
    entirely: every checked clip becomes a sequential segment, back-to-back,
    regardless of which row it came from. That's the "combine the clips I
    checked into one temp preview" behavior the Selected Clips scope needs.
    """
    timeline = resolve_timeline_multitrack(action_list)
    selected = set(instance_ids or [])
    clips = sorted((c for c in timeline if c["instanceId"] in selected), key=lambda c: (c["row"], c["col"]))
    if not clips:
        return None, "Selection is empty — nothing to render."

    segments = []
    try:
        for clip in clips:
            seg_path = render_segment(clip, available_list, use_proxy=use_proxy, preserve_alpha=False, overlay_setting=None)
            segments.append(seg_path)
    except Exception as e:
        return None, str(e)

    if not segments:
        return None, "Selection has nothing renderable."

    out_dir = RENDER_CACHE_DIR if use_proxy else EXPORT_DIR
    out_path = os.path.join(out_dir, f"selection_{uuid.uuid4().hex[:8]}.mp4")
    concat_files(segments, out_path, has_alpha=False)

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        return None, "Selected-clips render failed — check ffmpeg is on PATH and all source media is valid."

    labels = ", ".join(c["label"] for c in clips)
    return out_path, f"Concatenated {len(clips)} clip(s) sequentially: {labels}."

# --------------------------------------------------------------------------
# [SEC:PREVIEW-CUSTOM] Custom Selection: any combination of clips/rows/columns
# A 4th preview/export tier alongside Clip / Row / Grid. The user builds an
# arbitrary set of clips by clicking individual cells and/or whole row/column
# headers on a dedicated multi-select grid; Preview and Export both render
# that exact set through render_grid_composite(instance_ids=...) — the same
# function Grid level uses — so export is guaranteed to replicate preview.
# Matching UI: [SEC:UI-CUSTOM-SELECTION]. Matching wiring:
# [SEC:WIRING-CUSTOM-SELECTION].
#
# NOTE: this level picks WHICH whole clips are included (cell/row/column
# toggles), not WHAT PART of a clip's timeline is included — so it has no
# Selection bar/box and doesn't call parse_selection_string() /
# render_selection_within(). That point/band-timing mechanism (see
# [SEC:PREVIEW-CLIP] above) is what Clip, Row, and Grid level use to trim
# *within* the already-resolved timeline each of them produces; Custom
# Selection produces that timeline (the set of whole clips), it doesn't
# subdivide it. If a future feature wants in-clip trimming for a Custom
# Selection too, render_selection_within() is already shaped to take it —
# just needs a duration + a Selection box wired up the same way.
# --------------------------------------------------------------------------

def toggle_custom_selection_cell(bridge_value, selected_ids):
    if not bridge_value:
        return selected_ids
    instance_id = bridge_value.split("|")[0]
    selected_ids = list(selected_ids or [])
    if instance_id in selected_ids:
        selected_ids.remove(instance_id)
    else:
        selected_ids.append(instance_id)
    return selected_ids

def _toggle_custom_selection_group(bridge_value, action_list, selected_ids, group_key):
    if not bridge_value:
        return selected_ids
    try:
        group_value = int(bridge_value.split("|")[0])
    except (ValueError, IndexError):
        return selected_ids

    timeline = resolve_timeline_multitrack(action_list)
    group_ids = [c["instanceId"] for c in timeline if c[group_key] == group_value]
    selected_ids = list(selected_ids or [])
    if group_ids and all(i in selected_ids for i in group_ids):
        # Whole group already selected -> deselect it
        selected_ids = [i for i in selected_ids if i not in group_ids]
    else:
        for i in group_ids:
            if i not in selected_ids:
                selected_ids.append(i)
    return selected_ids

def toggle_custom_selection_row(bridge_value, action_list, selected_ids):
    return _toggle_custom_selection_group(bridge_value, action_list, selected_ids, "row")

def toggle_custom_selection_col(bridge_value, action_list, selected_ids):
    return _toggle_custom_selection_group(bridge_value, action_list, selected_ids, "col")

def toggle_custom_selection_all(bridge_value, action_list, selected_ids):
    """Toggle the entire grid — if every clip is already selected, deselect all;
    otherwise add every clip to the Custom Selection."""
    if not bridge_value:
        return selected_ids
    timeline = resolve_timeline_multitrack(action_list)
    all_ids = [c["instanceId"] for c in timeline]
    selected_ids = list(selected_ids or [])
    if all_ids and all(i in selected_ids for i in all_ids):
        # All already selected → deselect everything
        return []
    else:
        # Add any missing clip
        for i in all_ids:
            if i not in selected_ids:
                selected_ids.append(i)
        return selected_ids

def clear_custom_selection():
    return []

def auto_scope_from_selection(selected_ids):
    """Auto-switch the AI scope radio when custom selection changes.
    If clips are checked → switch to 'Selected Clips'.
    If selection is cleared → switch back to 'Clip'."""
    return "Selected Clips" if selected_ids else "Clip"    

def refresh_custom_selection_status(action_list, selected_ids):
    """Status line under Custom Selection. The grid itself is refreshed
    separately by refresh_working_grid (same Working Media Grid used
    everywhere), so this only recomputes the summary text."""
    timeline = resolve_timeline_multitrack(action_list)
    by_id = {c["instanceId"]: c for c in timeline}
    labels = [by_id[i]["label"] for i in (selected_ids or []) if i in by_id]
    status = (
        f"{len(labels)} clip(s) selected: {', '.join(labels)}"
        if labels else
        "No clips selected yet — click the +/\u2713 badge on a clip, or a row/column "
        "header, on the Working Media Grid above."
    )
    return status

def preview_custom_selection(action_list, available_list, selected_ids):
    if not selected_ids:
        return None, "Select at least one clip first (click cells, or a row/column header, above)."
    return render_grid_composite(action_list, available_list, use_proxy=True, instance_ids=selected_ids)

# --------------------------------------------------------------------------
# [SEC:AI-ASSISTANT] AI Command Execution & Mapping (integrates vibevideo.py)
# --------------------------------------------------------------------------

# Matches Working-Grid cell references like "R0C1" or "R2C3" (case-insensitive,
# whole word only so it won't fire inside an unrelated token).
GRID_CELL_REF_RE = re.compile(r'\bR(\d+)\s*C(\d+)\b', re.IGNORECASE)


def resolve_grid_name(query: str, action_list: list[dict], available_list: list[dict]) -> tuple[str, list[str]]:
    """Resolve Working-Grid cell references (e.g. `R0C1`, `R2C3`) inside a
    free-text AI command into the actual on-disk filename of the clip
    currently occupying that (row, col) cell.

    This lets a user type a command directly against the grid, e.g.:
        "Join R0C0 and R1C0"
    instead of having to know/type the underlying filename or use the
    file1/f1/[1] shortcuts.

    Case-insensitive; matches R<row>C<col> as a whole word. A reference to an
    empty cell or one whose source media can't be found is left untouched in
    the query (so the downstream NLP core will just fail to resolve it) and
    is called out in the returned notes for the AI Command Log.

    Returns (resolved_query, notes).
    """
    if not query:
        return query, []

    grid, _ = resolve_grid(action_list or [])
    notes: list[str] = []

    def _sub(match: "re.Match") -> str:
        row, col = int(match.group(1)), int(match.group(2))
        inst = grid.get((row, col))
        if inst is None:
            notes.append(f"R{row}C{col} \u2192 no clip at that grid cell (left unresolved)")
            return match.group(0)

        media = next((m for m in available_list if m["mediaId"] == inst.get("sourceMediaId")), None)
        if media is None:
            notes.append(f"R{row}C{col} \u2192 source media not found (left unresolved)")
            return match.group(0)

        dest_filename = os.path.basename(media["filepath"])
        notes.append(f"R{row}C{col} \u2192 '{dest_filename}'")
        return dest_filename

    resolved_query = GRID_CELL_REF_RE.sub(_sub, query)
    return resolved_query, notes


class LiveLogBuffer:
    """Thread-safe, StringIO-like log sink for live AI command streaming.

    Passed to contextlib.redirect_stdout() inside _run_ai_core() so every
    print() is accumulated for the final log AND immediately visible to the
    generator handlers, which poll getvalue() and stream it to the UI while
    the command is still running. Also mirrors writes to the real console.
    """

    def __init__(self):
        self._buffer = io.StringIO()
        self._lock = threading.Lock()
        self._console = sys.stdout  # captured before redirect_stdout() swaps sys.stdout

    def write(self, text):
        with self._lock:
            self._buffer.write(text)
        try:
            self._console.write(text)
        except Exception:
            pass
        return len(text)

    def flush(self):
        try:
            self._console.flush()
        except Exception:
            pass

    def getvalue(self):
        with self._lock:
            return self._buffer.getvalue()


def _start_ai_core_thread(live_log, **core_kwargs):
    """Runs _run_ai_core() in a daemon thread so the calling generator handler
    can stream live_log.getvalue() to the UI while the command executes.

    Returns (thread, holder): holder["result"] is _run_ai_core's return tuple,
    or holder["error"] is the exception if one escaped the core.
    """
    holder = {}

    def _worker():
        try:
            holder["result"] = _run_ai_core(live_log=live_log, **core_kwargs)
        except Exception as e:
            holder["error"] = e

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread, holder


def _run_ai_core(query, available_list, action_list=None, original_query=None, live_log=None):
    """Shared NLP command execution core (unmodified vibevideo.py NLP capabilities).

    Used by both the AI Command Assistant tab and the Visual Chessboard Editor's
    AI command input. Returns (available_list, log_output:list[str], outputs:list[str], preview_file).
    """
    if not query or not query.strip():
        return available_list, ["Please enter a command first."], [], None

    log_output = []
    display_original = original_query if original_query is not None else query
    log_output.append(f"Original Command: {display_original}")

    # 1. Resolve Working Grid cell references (R0C1, R2C3, ...) to actual filenames
    resolved_grid_query, grid_ref_notes = resolve_grid_name(query, action_list, available_list)
    if grid_ref_notes:
        log_output.append("Grid Cell References: " + "; ".join(grid_ref_notes))

    # 2. Build file mappings from current Gradio available list
    mapping = {}
    media_files = []
    
    for idx, m in enumerate(available_list, start=1):
        filename = m["filename"]
        dest_filename = os.path.basename(m["filepath"])
        
        mapping[filename.lower()] = dest_filename
        mapping[f"file{idx}"] = dest_filename
        mapping[f"f{idx}"] = dest_filename
        mapping[f"[{idx}]"] = dest_filename
        
        media_files.append(dest_filename)

    # 3. Add extra files in sample_media that might not be in the Gradio list yet
    for f in os.listdir(LIBRARY_DIR):
        if os.path.isfile(os.path.join(LIBRARY_DIR, f)) and f != "proxies":
            if f not in media_files:
                media_files.append(f)

    # 4. Preprocess query (filename / f1 / file1 / [1] shortcuts)
    processed_query = vibevideo.preprocess_query(resolved_grid_query, mapping)
    if processed_query != display_original:
        log_output.append(f"Resolved Command: {processed_query}")

    old_cwd = os.getcwd()
    outputs = []
    log_buffer = live_log if live_log is not None else io.StringIO()
    
    try:
        os.chdir(LIBRARY_DIR)
        
        # We redirect stdout so that print logs inside vibevideo.py are captured
        with contextlib.redirect_stdout(log_buffer):
            # Deterministic override detection (same as in vibevideo.py CLI loop)
            has_youtube_url = bool(re.search(vibevideo.YOUTUBE_URL_PATTERN, processed_query, re.I))
            wants_audio_only = bool(re.search(r'\b(mp3|audio)\b', processed_query, re.I))
            wants_video = bool(re.search(r'\b(video|subtitle|caption|srt)\b', processed_query, re.I))

            n_ranges = vibevideo.count_time_ranges(processed_query)
            is_delete = bool(re.search(r'\b(delete|remove|cut out)\b', processed_query, re.I))

            if has_youtube_url and wants_audio_only and not wants_video:
                multi_name, multi_distance = "youtube_to_mp3", 0.0
                print(f"[Tier 0] YouTube + audio-only -> direct route to '{multi_name}'")
            elif is_delete and n_ranges >= 1:
                multi_name, multi_distance = "delete_time_ranges", 0.0
                print(f"[Tier 0] Delete intent with {n_ranges} range(s) -> direct route to '{multi_name}'")
            elif n_ranges >= 2:
                multi_name, multi_distance = "multi_range_clip", 0.0
                print(f"[Tier 0] Multiple time ranges -> direct route to '{multi_name}'")
            else:
                multi_name, multi_distance = vibevideo.search_multicommands(processed_query)

            if multi_name is not None and multi_distance < vibevideo.MULTICOMMAND_MAX_DISTANCE:
                print(f"[Tier 1] Matched multicommand '{multi_name}' (distance={multi_distance:.3f})")
                input_files = vibevideo.resolve_multicommand_input_files(processed_query, media_files)
                from multicommand.multi_executor import execute_multicommand
                result = execute_multicommand(multi_name, processed_query, input_files)
                outputs = result if isinstance(result, list) else [result]
            else:
                if multi_distance is not None:
                    print(f"[Tier 1] No confident multicommand match (best='{multi_name}', distance={multi_distance:.3f}); falling back to single command.")
                
                chunk, distance = vibevideo.search_documents(processed_query)
                capability = chunk["text"].split("\n")[0]
                print(f"Matched capability: '{capability}' (distance={distance:.3f})")
                
                params = vibevideo.parse_parameters(processed_query)
                print(f"Parsed parameters: {params}")
                
                from mcp.instruction import find_mcp_instruction
                from mcp.capability_resolver import resolve_tool
                from mcp.executor import execute as execute_tool_instruction
                
                instruction = find_mcp_instruction(capability, params)
                tool = resolve_tool(instruction)
                print(f"Resolved tool: {tool}")
                
                result = execute_tool_instruction(tool, instruction)
                outputs = result if isinstance(result, list) else [result]

    except Exception as e:
        log_output.append(log_buffer.getvalue())
        log_output.append(f"Error running command: {e}")
        os.chdir(old_cwd)
        return available_list, log_output, [], None

    finally:
        os.chdir(old_cwd)

    # Gather logs
    log_output.append(log_buffer.getvalue())

    # 5. Scan sample_media/ for newly created files to ingest them into the library
    available_list = scan_existing_files(available_list)
    
    # 6. Try to find the output file to load in preview video player
    preview_file = None
    log_output.append(f"Generated Outputs: {outputs}")
    for out in outputs:
        if not out:
            continue
        out_path = out if os.path.isabs(out) else os.path.join(LIBRARY_DIR, out)
        if os.path.exists(out_path):
            mtype = infer_media_type(out)
            if mtype in ("video", "audio"):
                preview_file = out_path
                break

    # If preview_file is still None, look for the newest file in LIBRARY_DIR
    if not preview_file:
        files = [os.path.join(LIBRARY_DIR, f) for f in os.listdir(LIBRARY_DIR) if os.path.isfile(os.path.join(LIBRARY_DIR, f))]
        if files:
            newest_file = max(files, key=os.path.getmtime)
            mtype = infer_media_type(newest_file)
            if mtype in ("video", "audio") and os.path.basename(newest_file) != "proxies":
                preview_file = newest_file

    log_output.append("AI Command Execution completed successfully.")
    return available_list, log_output, outputs, preview_file


def run_ai_command(query, available_list, action_list):
    """AI Command Assistant tab handler — free-text query, with Working Grid
    cell references (R0C1, R2C3, ...) resolved to filenames via resolve_grid_name().

    Generator handler: the NLP core runs in a background thread while this
    generator polls the live log and streams progress into 'AI Command Logs'.
    """
    live_log = LiveLogBuffer()
    thread, holder = _start_ai_core_thread(
        live_log, query=query, available_list=available_list, action_list=action_list,
    )
    while thread.is_alive():
        yield gr.update(), gr.update(), live_log.getvalue(), gr.update(), gr.update(), gr.update()
        time.sleep(0.3)
    thread.join()

    if "error" in holder:
        error_text = f"{live_log.getvalue()}\nError running command: {holder['error']}"
        yield gr.update(), gr.update(), error_text, gr.update(), gr.update(), gr.update()
        return

    available_list, log_output, outputs, preview_file = holder["result"]

    choices = [f'{m["mediaId"]} | {m["filename"]}' for m in available_list]
    dropdown_update = gr.Dropdown(choices=choices)
    mapping_df = render_mapping_df(available_list)
    available_df_val = render_available_df(available_list)

    yield available_list, available_df_val, "\n".join(log_output), preview_file, mapping_df, dropdown_update


def finalize_ai_output_target(preview_path):
    """Feeds the AI Command Assistant's result into the one shared Preview
    screen + one shared Selection system (mirrors set_preview_target_raw),
    run as a follow-up step so run_ai_command()'s own NLP/vibevideo logic
    stays untouched."""
    if not preview_path:
        return None, _unified_sel_bar(0.1), "AI command produced no previewable output — see AI Command Logs below."
    target, sel_bar_html = set_preview_target_raw(preview_path, "AI Output")
    duration = target["duration"] if target else 0.0
    status = f"AI Output — {os.path.basename(preview_path)} ({duration:.2f}s)."
    return target, sel_bar_html, status


# --------------------------------------------------------------------------
# [SEC:AI-CHESSBOARD] AI Command Input for the Visual Chessboard Editor
# --------------------------------------------------------------------------
# Same NLP execution as the AI Command Assistant tab, except the file
# reference(s) fed to the AI engine are resolved automatically from the
# Chessboard selection — the target clip instance, a whole row, or the
# entire grid — instead of being typed inline in the command. Whatever
# media file(s) the command produces are placed straight back onto the
# Grid / Active List, so every existing preview (clip / row / grid) and the
# final export automatically pick it up — they all read from the same
# action_state / available_state.

def resolve_scope_files(scope, instance_choice, row_number, action_list, available_list, custom_selected_ids=None):
    """Resolve the underlying source file name(s) for the given AI scope.

    `row_number` is the shared "Row number" field (also used to drive the
    Row Preview's Selection bar), used only when scope == "Row".

    `custom_selected_ids` is the list of instanceIds checked on the Working
    Grid — used only when scope == "Selected Clips".

    Returns (filenames: list[str], clips: list[dict]) where `clips` are the
    resolved timeline entries (in row/col order) backing those filenames.
    """
    timeline = resolve_timeline_multitrack(action_list)

    if scope == "Clip":
        instance_id = parse_instance_choice(instance_choice)
        clip = next((c for c in timeline if c["instanceId"] == instance_id), None)
        clips = [clip] if clip else []
    elif scope == "Selected Clips":
        selected_set = set(custom_selected_ids or [])
        if not selected_set:
            return [], []
        clips = sorted(
            (c for c in timeline if c["instanceId"] in selected_set),
            key=lambda c: (c["row"], c["col"]),
        )
    elif scope == "Row":
        if row_number in (None, ""):
            return [], []
        row = int(row_number)
        clips = sorted((c for c in timeline if c["row"] == row), key=lambda c: c["col"])
    else:  # "Entire Grid"
        clips = sorted(timeline, key=lambda c: (c["row"], c["col"]))

    names = []
    for c in clips:
        media = next((m for m in available_list if m["mediaId"] == c["sourceMediaId"]), None)
        if media:
            names.append(media["filename"])
    return names, clips


def build_chessboard_ai_query(query, file_names, timing_text):
    """Resolve the scope-selected file name(s) and timing into the command text.

    If the typed command contains `{files}` / `{time}` placeholders they are
    substituted directly; otherwise the resolved references are appended.
    """
    file_refs = ", ".join(file_names) if file_names else ""

    time_refs = ""
    if timing_text and timing_text.strip():
        try:
            selections = parse_selection_string(timing_text)
        except ValueError:
            selections = []
        phrases = []
        for s in selections:
            if s["type"] == "point":
                phrases.append(f'at {s["time"]:.2f} seconds')
            else:
                phrases.append(f'from {s["start"]:.2f} to {s["end"]:.2f} seconds')
        time_refs = " and ".join(phrases)

    final_query = (query or "").strip()

    if "{files}" in final_query:
        final_query = final_query.replace("{files}", file_refs)
    elif file_refs and not GRID_CELL_REF_RE.search(final_query):
        final_query = f"{final_query} {file_refs}".strip()

    if "{time}" in final_query:
        final_query = final_query.replace("{time}", time_refs)
    elif time_refs:
        final_query = f"{final_query} {time_refs}".strip()

    return final_query


def place_media_on_grid(media, target_row, target_col, action_list):
    """Same placement logic as add_to_active(), factored out for reuse."""
    if target_row in (None, ""):
        timeline = resolve_timeline(action_list)
        target_row = (max((c["row"] for c in timeline), default=-1)) + 1
    else:
        target_row = int(target_row)

    grid, _ = resolve_grid(action_list)
    if target_col in (None, ""):
        existing_cols = [c for (r, c) in grid.keys() if r == target_row]
        target_col = (max(existing_cols, default=-1)) + 1
    else:
        target_col = int(target_col)
        while (target_row, target_col) in grid:
            target_col += 1

    # Ensure proxy is generated for clips placed on the working grid
    ensure_proxy(media)

    instance_id = f"clip_{uuid.uuid4().hex[:6]}"
    action_list.append(make_action(instance_id, "ADD", {
        "sourceMediaId": media["mediaId"],
        "mediaType": media.get("mediaType", "video"),
        "inPoint": 0.0,
        "outPoint": media["duration"],
        "row": target_row,
        "col": target_col,
    }))
    return action_list, target_row, target_col, instance_id


def replace_clip_media(instance_id, media, action_list):
    """In-place edit: swap a clip's source file for the AI result, keeping its cell."""
    ensure_proxy(media)
    action_list.append(make_action(instance_id, "REPLACE", {"newSourceMediaId": media["mediaId"]}))
    action_list.append(make_action(instance_id, "TRIM", {"newIn": 0.0, "newOut": media["duration"]}))
    return action_list


def run_ai_command_chessboard(
    query, scope, instance_choice, row_number,
    selection_text,
    target_row, target_col, available_list, action_list,
    custom_selected_ids,
):
    """Visual Chessboard Editor's AI command handler.

    Resolves both the source file name(s) *and* the timing entirely from
    the Grid/selection system — nothing is typed manually:
      - Files come from the current scope (Clip / Row / Entire Grid), via
        resolve_scope_files().
      - Timing comes from the one shared Selection box (unified_sel_box) —
        the same box used by "Preview Selection" everywhere else in the
        app. Leave it empty to run against the whole clip/row/grid.

    Runs the same NLP core as the AI Command Assistant, then writes the
    result back:
      - Clip scope: edits the selected clip in place (REPLACE + TRIM), so
        the same grid cell / Active List row just gets a new source file.
      - Row / Entire Grid scope: adds the result as a new clip (ADD) at the
        requested row/col, since it represents a composite of multiple clips.
    Every downstream preview (clip/row/grid) and the final export read the
    returned action_state/available_state, so they pick the result up
    automatically.
    """
    def current_state(logs):
        choices = [f'{m["mediaId"]} | {m["filename"]}' for m in available_list]
        return (
            available_list, action_list,
            render_available_df(available_list), render_active_df(action_list), render_action_df(action_list),
            render_working_grid_html(action_list, None, row_number, custom_selected_ids),
            gr.Dropdown(choices=instance_choices(action_list), value=None),
            gr.Dropdown(choices=choices),
            render_mapping_df(available_list),
            logs,
        )

    if not query or not query.strip():
        yield current_state("Please enter a command first.")
        return

    file_names, source_clips = resolve_scope_files(scope, instance_choice, row_number, action_list, available_list, custom_selected_ids)
    if not file_names:
        hint = {
            "Clip": "Select a target clip instance in Actions below first.",
            "Selected Clips": "Check at least one clip on the Working Grid first (click the +/✓ badge).",
            "Row": "Enter a valid 'Row number' under Row Preview / Export first.",
            "Entire Grid": "The grid is empty — add some clips first.",
        }.get(scope, "No source files could be resolved for this scope.")
        yield current_state(f"No source file(s) resolved for scope '{scope}'. {hint}")
        return

    # If scope is Row, Entire Grid, or Selected Clips, render the sequence into
    # a single temporary file first so the AI editing commands run on the whole
    # timeline instead of individual files.
    if scope in ("Row", "Entire Grid", "Selected Clips"):
        yield (gr.update(),) * 9 + (f"Preparing {scope.lower()} timeline for AI processing…",)
        safe_scope = scope.lower().replace(" ", "_")
        temp_name = f"{safe_scope}_{uuid.uuid4().hex[:6]}.mp4"
        temp_path = os.path.join(LIBRARY_DIR, temp_name)
        try:
            if scope == "Row":
                out_path, render_note = render_row(action_list, available_list, int(row_number), use_proxy=False)
            elif scope == "Selected Clips":
                out_path, render_note = render_selected_clips_sequential(
                    action_list, available_list, list(custom_selected_ids or []), use_proxy=False,
                )
            else:  # Entire Grid
                out_path, render_note = render_grid_composite(action_list, available_list, use_proxy=False)

            if out_path and os.path.exists(out_path):
                shutil.copy(out_path, temp_path)
                # Ingest the temp file so the AI engine can resolve it
                available_list = scan_existing_files(available_list)
                file_names = [temp_name]
            else:
                yield current_state(f"Failed to render {scope.lower()} timeline for AI processing. {render_note or ''}".strip())
                return
        except Exception as e:
            yield current_state(f"Error rendering {scope.lower()} timeline: {e}")
            return

    timing_text = selection_text or ""

    final_query = build_chessboard_ai_query(query, file_names, timing_text)

    before_paths = {os.path.abspath(m["filepath"]) for m in available_list}
    scope_log = f"Scope: {scope} → source file(s): {', '.join(file_names)}"
    if timing_text and timing_text.strip():
        scope_log += f" | selection: {timing_text.strip()}"

    live_log = LiveLogBuffer()
    thread, holder = _start_ai_core_thread(
        live_log, query=final_query, available_list=available_list,
        action_list=action_list, original_query=query,
    )
    while thread.is_alive():
        yield (gr.update(),) * 9 + (f"{scope_log}\n{live_log.getvalue()}",)
        time.sleep(0.3)
    thread.join()

    if "error" in holder:
        error_text = f"{scope_log}\n{live_log.getvalue()}\nError running command: {holder['error']}"
        yield (gr.update(),) * 9 + (error_text,)
        return

    available_list, log_output, outputs, preview_file = holder["result"]
    log_output = [scope_log] + log_output

    command_input_paths = {os.path.abspath(os.path.join(LIBRARY_DIR, f)) for f in file_names}

    # Match produced output(s) back to entries in the (now refreshed) available_list
    new_media = []
    seen_ids = set()
    for out in outputs:
        if not out:
            continue
        out_path = out if os.path.isabs(out) else os.path.join(LIBRARY_DIR, out)
        media = next((m for m in available_list if os.path.abspath(m["filepath"]) == os.path.abspath(out_path)), None)
        if media and media["mediaId"] not in seen_ids:
            if os.path.abspath(media["filepath"]) not in before_paths or os.path.abspath(media["filepath"]) not in command_input_paths:
                new_media.append(media)
                seen_ids.add(media["mediaId"])

    if not new_media and preview_file:
        media = next((m for m in available_list if os.path.abspath(m["filepath"]) == os.path.abspath(preview_file)), None)
        if media and (os.path.abspath(media["filepath"]) not in before_paths or os.path.abspath(media["filepath"]) not in command_input_paths):
            new_media.append(media)

    if not new_media:
        log_output.append("No new media file was produced by this command, so the Grid was not changed.")
        yield current_state("\n".join(log_output))
        return

    if scope == "Clip":
        clip = source_clips[0]
        first, rest = new_media[0], new_media[1:]
        action_list = replace_clip_media(clip["instanceId"], first, action_list)
        log_output.append(f"Replaced clip at R{clip['row']}C{clip['col']} in place with AI result '{first['filename']}'.")
        # Any extra outputs (rare for a single-clip command) land next to it on the same row.
        row_arg, col_arg = None, None
        for media in rest:
            action_list, placed_row, placed_col, _ = place_media_on_grid(media, clip["row"], None, action_list)
            log_output.append(f"Placed additional AI result '{media['filename']}' onto Grid at R{placed_row}C{placed_col}.")
    else:
        row_arg, col_arg = target_row, target_col
        for media in new_media:
            action_list, placed_row, placed_col, _ = place_media_on_grid(media, row_arg, col_arg, action_list)
            log_output.append(f"Placed AI result '{media['filename']}' onto Grid at R{placed_row}C{placed_col}.")
            row_arg, col_arg = None, None  # subsequent outputs auto-place on new rows

    yield current_state("\n".join(log_output))


# --------------------------------------------------------------------------
# [SEC:STARTUP] Startup Event Trigger
# --------------------------------------------------------------------------

# Loading spinner HTML shown immediately in the library grid area while the
# slow scan (proxy generation etc.) runs in the background step.
_LIBRARY_LOADING_HTML = """
<div style="
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    height:220px; gap:14px; color:#888; font-family:sans-serif;">
  <div style="
      width:48px; height:48px; border:5px solid #e0e0e0;
      border-top-color:#6366f1; border-radius:50%;
      animation:vv-spin 0.9s linear infinite;">
  </div>
  <div style="font-size:15px; font-weight:500;">Updating media library&hellip;</div>
  <div style="font-size:12px; color:#aaa;">Please wait while your files are being scanned.</div>
</div>
<style>
  @keyframes vv-spin { to { transform: rotate(360deg); } }
</style>
"""

def on_load_show_spinner():
    """Step 1: runs instantly on page load — shows a loading spinner in the
    library grid so the user gets immediate feedback while the slow scan runs."""
    return _LIBRARY_LOADING_HTML

def on_load_trigger(available_list):
    """Step 2: runs after the spinner is shown — scans sample_media/ and
    generates proxies for any new video files (may be slow on first boot)."""
    available_list = scan_existing_files(available_list)
    df = render_available_df(available_list)
    dropdown_choices = [f'{m["mediaId"]} | {m["filename"]}' for m in available_list]
    mapping_df = render_mapping_df(available_list)
    status_msg = f"Scanned library. Loaded {len(available_list)} pre-existing media files."
    return (
        available_list,
        df,
        status_msg,
        gr.Dropdown(choices=dropdown_choices),
        mapping_df
    )

# --------------------------------------------------------------------------
# [SEC:UI-LAYOUT] UI Blocks Layout
# All UI components live in one `with gr.Blocks()` scope (Gradio requires
# this), organized into bannered sub-sections below matching the backend
# sections that power them. See [SEC:WIRING-*] further down for how each
# button/control is connected to its handler function.
# --------------------------------------------------------------------------

CUSTOM_CSS = """
    .vv-hidden-bridge { display: none !important; }
    .ai-logs { font-family: monospace; font-size: 13px; line-height: 1.4; }

    /* ---- [VV-PERF 1/2] Stacked tabs ----------------------------------
       Gradio shows/hides tab panels by flipping an inline display:flex/none,
       which forces a full re-style + re-layout of the newly shown panel's
       entire subtree on every switch. Here both panels are kept permanently
       laid out, overlapped in one grid cell; switching only flips paint.
       Zero JavaScript: Gradio marks the active panel purely by its inline
       "display: flex" style, so CSS attribute selectors can detect it. */
    #vv-main-tabs { display: grid !important; }
    #vv-main-tabs > *:not([role="tabpanel"]) { grid-area: 1 / 1; }
    #vv-main-tabs > div[role="tabpanel"] {
        display: block !important;
        grid-area: 2 / 1;
        visibility: hidden;
        opacity: 0;
        pointer-events: none;
    }
    #vv-main-tabs > div[role="tabpanel"][style*="display: flex"],
    #vv-main-tabs > div[role="tabpanel"][style*="display:flex"] {
        visibility: visible;
        opacity: 1;
        pointer-events: auto;
    }

    /* ---- [VV-PERF 2/2] Shared classes for the Media Library tiles and
       the Working Grid chessboard (replaces per-tile inline styles) ---- */
    .vv-f-video   { color:#2d6cdf; }
    .vv-f-audio   { color:#2da65a; }
    .vv-f-image   { color:#c98a1c; }
    .vv-f-subtitle{ color:#8a3fd1; }
    .vv-b-video   { border-color:#2d6cdf; }
    .vv-b-audio   { border-color:#2da65a; }
    .vv-b-image   { border-color:#c98a1c; }
    .vv-b-subtitle{ border-color:#8a3fd1; }

    /* Media Library tile grid */
    .vv-lib-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(150px, 1fr)); gap:8px; padding:4px; }
    .vv-tile     { position:relative; border-radius:6px; overflow:hidden; cursor:pointer; background:#1a1a1a; border:1px solid #666; }
    .vv-tile.vv-sel { border-width:3px; }
    .vv-tile-img { width:100%; height:90px; object-fit:cover; display:block; }
    .vv-tile-ph  { width:100%; height:90px; display:flex; align-items:center; justify-content:center; font-size:32px; }
    .vv-tile-meta{ padding:4px 6px; font-size:11px; color:#ccc; word-break:break-word; }
    .vv-tile-dur { color:#777; font-size:10px; }
    .vv-check    { position:absolute; top:4px; right:4px; background:#000a; color:#4f4; border-radius:50%; width:18px; height:18px; font-size:12px; line-height:18px; text-align:center; }

    /* Working Grid chessboard */
    .vv-wg-scroll { overflow-x:auto; }
    .vv-wg-legend { margin-bottom:6px; font-size:12px; }
    .vv-wg-note   { margin-bottom:4px; font-size:11px; color:#888; }
    .vv-wg-table  { border-collapse:collapse; }
    .vv-corner    { width:36px; cursor:pointer; text-align:center; vertical-align:middle; }
    .vv-colh      { padding:4px 6px; font-size:12px; color:#888; cursor:pointer; text-align:center; white-space:nowrap; }
    .vv-colh.vv-sel  { color:#fff; }
    .vv-colh-in   { display:flex; flex-direction:column; align-items:center; gap:1px; }
    .vv-toggle    { display:inline-block; width:14px; height:14px; line-height:14px; font-size:10px; text-align:center; border-radius:3px; background:#0006; color:#aaa; cursor:pointer; }
    .vv-toggle.vv-sel { background:#1f8f3f; color:#fff; }
    .vv-colh-in .vv-toggle { margin-bottom:2px; }
    .vv-rowlab .vv-toggle  { margin-right:4px; }
    .vv-rowlab    { padding:4px 8px; font-size:12px; white-space:nowrap; color:#888; }
    .vv-rowlab.vv-rowsel { color:#fff; background:#2d6cdf33; border:2px solid #2d6cdf; font-weight:bold; }
    .vv-rowname   { cursor:pointer; }
    .vv-offbadge  { color:#888; font-size:11px; }
    .vv-cell      { width:64px; height:48px; border:1px solid #333; text-align:center; color:#444; }
    .vv-cell.vv-rs   { background:#2d6cdf11; }
    .vv-cell-filled{ position:relative; width:64px; height:48px; border:1px solid #333; text-align:center; font-size:12px; vertical-align:middle; cursor:pointer; }
    .vv-cell-filled.vv-cellsel { border-width:3px; }
    .vv-g-video   { background:#2d6cdf22; }
    .vv-g-audio   { background:#2da65a22; }
    .vv-g-image   { background:#c98a1c22; }
    .vv-g-subtitle{ background:#8a3fd122; }
    .vv-g-video.vv-cs   { background:#2d6cdf55; }
    .vv-g-audio.vv-cs   { background:#2da65a55; }
    .vv-g-image.vv-cs   { background:#c98a1c55; }
    .vv-g-subtitle.vv-cs{ background:#8a3fd155; }
    .vv-g-video.vv-rs   { background:#2d6cdf33; }
    .vv-g-audio.vv-rs   { background:#2da65a33; }
    .vv-g-image.vv-rs   { background:#c98a1c33; }
    .vv-g-subtitle.vv-rs{ background:#8a3fd133; }
    .vv-badge     { position:absolute; top:2px; right:2px; width:14px; height:14px; line-height:14px; font-size:10px; text-align:center; border-radius:3px; cursor:pointer; background:#0006; color:#ccc; }
    .vv-badge.vv-sel { background:#1f8f3f; color:#fff; }
    .vv-ovbadge   { position:absolute; bottom:2px; left:2px; font-size:9px; color:#00e5ff; background:#000a; padding:1px 3px; border-radius:2px; }
    .vv-cellpos   { font-size:10px; }
"""

with gr.Blocks(
    title="VibeVideo — Editor",
) as demo:
    gr.Markdown("# VibeVideo — Editor (Tier 1: Gradio)")

    available_state = gr.State([])   # list of media dicts
    action_state = gr.State([])      # append-only action log
    custom_selection_state = gr.State([])   # list of instanceIds picked in Custom Selection
    library_selection_state = gr.State(None)   # mediaId currently selected in the Media Library grid (or None)
    library_added_instances_state = gr.State({})   # {mediaId: instanceId} for clips auto-added by selecting a Library Grid tile — lets deselecting it remove exactly that clip from the Working Grid
    preview_target_state = gr.State(None)   # {"kind", ...params, "duration", "label"} — what's on the ONE shared Preview screen right now

    with gr.Tabs(elem_id="vv-main-tabs"):
        # TAB 1: Visual Timeline Editor (Exact layout and controls of app.py)
        with gr.Tab("Visual Chessboard Editor", render_children=True):
            with gr.Row():
                # ---------------- [SEC:UI-AVAILABLE-LIST] Available List ----------------
                with gr.Column(scale=1):
                    gr.Markdown("### Available List")
                    file_upload = gr.File(label="Add media", file_count="multiple")
                    default_image_duration_in = gr.Number(
                        label="Default image duration (sec)",
                        value=DEFAULT_DURATION["image"],
                        minimum=0.1,
                        info="Applied to images at upload time — a row of "
                             "several images just runs that many seconds "
                             "each, back-to-back. Trim a clip afterwards to "
                             "fine-tune it.",
                    )
                    upload_status = gr.Markdown("")
                    with gr.Accordion("Library list", open=False):
                        available_df = gr.Dataframe(
                            headers=["mediaId", "filename", "mediaType", "duration"],
                            label="Library", interactive=False,
                        )

                    gr.Markdown(
                        "### Library Grid\n"
                        "Full filename + thumbnail per tile, color-coded by "
                        "type. Click a tile to select it — it's added "
                        "straight to the **Working Grid** right away, at the "
                        "current Row/Col fields below (preview it first if "
                        "you want to check it). Click it again to deselect "
                        "— this removes that clip from the Working Grid too "
                        "(if you've since arranged it, use the Working "
                        "Grid's own Remove instead, which won't touch this "
                        "tile's checkmark)."
                    )
                    with gr.Row():
                        library_sort_key = gr.Radio(
                            LIBRARY_SORT_KEYS, value="Date Created", label="Sort by",
                        )
                        library_sort_dir = gr.Radio(
                            LIBRARY_SORT_DIRS, value="Descending", label="Order",
                        )
                    library_grid_html = gr.HTML(render_media_library_grid_html([]))
                    library_click_bridge = gr.Textbox(elem_id="library_click_bridge", elem_classes=["vv-hidden-bridge"], value="")
                    gr.Markdown("_Clicking a tile shows it in the shared Preview window →_")

                    # media_dropdown, add_row_in, add_col_in, add_active_btn kept hidden —
                    # Library tile click still uses add_row_in/add_col_in as inputs and
                    # media_dropdown as an output; add_active_btn wiring is preserved too.
                    media_dropdown = gr.Dropdown(label="Select media to add", choices=[], visible=False)
                    add_row_in = gr.Number(label="Row / track (blank = next new row)", value=None, visible=False)
                    add_col_in = gr.Number(label="Column (blank = end of row)", value=None, visible=False)
                    add_active_btn = gr.Button("Add to Working Grid →", visible=False)

                    # ---------------- [SEC:UI-CHESSBOARD-AI] AI Command (Chessboard) ----------------
                    gr.Markdown("### AI Command (Chessboard)")
                    gr.Markdown(
                        "Same NLP engine as the AI Command Assistant tab, but "
                        "the file name(s) *and* timing fed to it are pulled "
                        "automatically from the Grid — no typing labels or "
                        "times into the command. Use `{files}` / `{time}` in "
                        "your command to control where they're inserted, "
                        "otherwise they're appended automatically."
                    )
                    cb_ai_scope = gr.Radio(
                        ["Clip", "Selected Clips", "Row", "Entire Grid"],
                        value="Clip",
                        label="Apply AI command to",
                    )
                    gr.Markdown(
                        "Each scope pulls its file(s) from the matching "
                        "section below — nothing to fill in here:\n"
                        "- **Clip**: the *Target clip instance* (Actions).\n"
                        "- **Selected Clips**: the clips currently checked on the Working Grid (the +/✓ badges). "
                        "They are concatenated in Row/Col order into one temporary video before the command runs.\n"
                        "- **Row**: the **Row number** under *Row Preview*.\n"
                        "- **Entire Grid**: the whole grid.\n\n"
                        "Timing for all scopes comes from the one shared "
                        "**Selection** box above the Preview window — leave "
                        "it empty to run the command against the whole "
                        "clip/row/grid instead of a sub-range.\n\n"
                        "**Clip** edits that clip in place (same cell, source "
                        "file swapped to the AI result). **Selected Clips** / **Row** / **Entire "
                        "Grid** add the AI result as a new clip."
                    )
                    cb_ai_query = gr.Textbox(
                        label="AI Editing Command",
                        placeholder="e.g. trim {files} {time} as output.mp4",
                        lines=2,
                    )
                    with gr.Row():
                        cb_ai_row_in = gr.Number(label="Place result at row (Row/Grid scope; blank = next new row)", value=None)
                        cb_ai_col_in = gr.Number(label="Place result at column (Row/Grid scope; blank = end of row)", value=None)
                    cb_run_ai_btn = gr.Button("Execute AI Command → Add to Grid", variant="primary")
                    cb_ai_logs = gr.Textbox(
                        label="AI Command Logs", elem_classes=["ai-logs"], interactive=False, lines=10,
                    )

                # ---------------- [SEC:UI-GRID-ACTIONS] Working Grid (Grid + Actions, with the old
                # Active List / dropdown functions folded directly in as supporting controls) ----------------
                with gr.Column(scale=2):
                    gr.Markdown("### Preview")
                    # ---------------- [SEC:UI-UNIFIED-PREVIEW] ----------------
                    gr.Markdown(
                        "**One shared preview window for every preview action in "
                        "the app** — a single clip, a clip's in-clip selection, a "
                        "row, a row's selection, the whole grid, the grid's "
                        "selection, or a Custom Selection of any clips/rows/"
                        "columns. Whichever one you last previewed shows here; "
                        "the status line below always says what it is."
                    )
                    unified_preview_video = gr.Video(label="Preview", show_label=True, interactive=False, buttons=["download"])
                    unified_preview_status = gr.Markdown("Click a clip on the Grid, or use any Preview button below, to see it here.")

                    gr.Markdown("### Working Grid")
                    gr.Markdown(
                        "This is where media from the **Library Grid** lands "
                        "and where you arrange it. **Row = track** (video/"
                        "audio/image/subtitle layer), **column = ordering "
                        "position within that row** — not a shared time-slot. "
                        "Each row plays its own clips back-to-back, full length, "
                        "in column order, at its own pace; adding several short "
                        "clips (e.g. a run of images) just makes that row take "
                        "longer, with no effect on any other row. Labels are "
                        "**R{row}C{col}** — same instance, same "
                        "name, everywhere in the app. Click a clip to select "
                        "it (this sets *Target clip instance* below, so "
                        "Trim/Move/Copy/Remove/Undo and the AI Clip scope "
                        "all act on it) and preview it instantly, or click a "
                        "row label to select that row. Color = media type: "
                        + " &nbsp; ".join(
                            f'<span style="color:{MEDIA_TYPE_COLOR[t]};">{MEDIA_TYPE_ICON[t]} {t}</span>'
                            for t in MEDIA_TYPE_ICON
                        ) + "\n\n"
                        "Use the arrows below to move the selected clip — "
                        "moving onto an occupied cell swaps the two clips. "
                        "Shifting a row delays/advances that whole track "
                        "without reordering it. This one grid also drives "
                        "the Custom Selection further down — click a clip's "
                        "small **+/\u2713** badge, or a row/column header's "
                        "own toggle, to add/remove it there without leaving "
                        "the single-selection you're using for Trim/Move/"
                        "Copy/Remove/Row Preview."
                    )
                    working_grid_html = gr.HTML(render_working_grid_html([]))
                    grid_click_bridge = gr.Textbox(elem_id="grid_click_bridge", elem_classes=["vv-hidden-bridge"], value="")
                    row_click_bridge = gr.Textbox(elem_id="row_click_bridge", elem_classes=["vv-hidden-bridge"], value="")

                    with gr.Row():
                        move_up_btn = gr.Button("\u2191 Up")
                        move_down_btn = gr.Button("\u2193 Down")
                        move_left_btn = gr.Button("\u2190 Left")
                        move_right_btn = gr.Button("\u2192 Right")

                    with gr.Row():
                        shift_row_in = gr.Number(label="Row to shift", value=None)
                        shift_seconds_in = gr.Number(label="Shift by (seconds, +/-)", value=None)
                        shift_row_btn = gr.Button("Shift Row")

                    gr.Markdown(
                        "**Layering (which row is the base)** — among "
                        "overlapping visual (video/image) rows, whichever "
                        "has the lowest layer priority number becomes the "
                        "full-canvas base; every other visual row overlays "
                        "on top. Defaults to row number (row 0 base, row 1 "
                        "overlay, etc.) until you set one — fully swappable."
                    )
                    with gr.Row():
                        zindex_row_in = gr.Number(label="Row", value=None)
                        zindex_value_in = gr.Number(label="Layer priority (lower = more toward base)", value=None)
                        zindex_set_btn = gr.Button("Set Layer Priority")
                    zindex_status = gr.Markdown("")

                    gr.Markdown(
                        "**Overlay settings for non-base rows** — pick a "
                        "resizable/repositionable picture-in-picture inset "
                        "(corner + size), or **full** for a full-canvas "
                        "overlay that preserves real PNG transparency (a "
                        "logo/watermark image with a transparent background "
                        "shows the row beneath it through the transparent "
                        "areas, instead of being flattened to opaque black)."
                    )
                    with gr.Row():
                        overlay_row_in = gr.Number(label="Row to set overlay for", value=None)
                        overlay_scale_in = gr.Slider(label="PIP width (% of canvas, ignored for 'full')", minimum=10, maximum=100, step=5, value=40)
                        overlay_corner_in = gr.Dropdown(
                            label="Corner / mode",
                            choices=["top-right", "top-left", "bottom-right", "bottom-left", "center", "full"],
                            value="top-right",
                        )
                        overlay_set_btn = gr.Button("Set Overlay")
                    overlay_status = gr.Markdown("")

                    gr.Markdown(
                        "**Clip Overlay & Screen Position (for non-base rows)** — set screen "
                        "position and size for **this specific clip** when its row is an overlay. "
                        "Allows multiple clips on the same row to appear at different corners / center / full canvas."
                    )
                    with gr.Row():
                        clip_overlay_mode = gr.Dropdown(
                            label="Position Mode",
                            choices=["Inherit from Row", "Custom Position"],
                            value="Inherit from Row",
                        )
                        clip_overlay_corner = gr.Dropdown(
                            label="Corner / Alignment",
                            choices=["top-right", "top-left", "bottom-right", "bottom-left", "center", "full"],
                            value="top-right",
                        )
                        clip_overlay_scale = gr.Slider(
                            label="Clip Size (% width, ignored for 'full')",
                            minimum=10, maximum=100, step=5, value=40,
                        )
                    with gr.Row():
                        clip_overlay_set_btn = gr.Button("Set Clip Position")
                        clip_overlay_reset_btn = gr.Button("Reset Clip to Row Default")
                    clip_overlay_status = gr.Markdown("")

                    gr.Markdown("### Selection")
                    gr.Markdown(
                        "**One shared selection system for everything on the "
                        "Preview window above.** Click/drag the bar below, or "
                        "type directly — e.g. `10-15, 22.3, 40-45` (bands as "
                        "`start-end`, points as a single number, comma-"
                        "separated). Applies to whatever you last previewed: "
                        "a clip, a row, the grid, a Custom Selection, a "
                        "Library tile, or an AI result."
                    )
                    unified_sel_bar_html = gr.HTML(render_selection_bar_html(0.1, "unified_sel_bar", "unified_sel_box"))
                    unified_sel_box = gr.Textbox(label="Selection", elem_id="unified_sel_box", value="")
                    with gr.Row():
                        unified_sel_preview_btn = gr.Button("Preview Selection")
                        unified_sel_clear_btn = gr.Button("Clear Selection")

                    gr.Markdown("### Export")
                    gr.Markdown(
                        "**One export button for everything on the Preview "
                        "window above.** If a Selection is typed in, only "
                        "that trimmed sub-range is exported; otherwise the "
                        "whole clip/row/grid/selection/library file/AI "
                        "result is exported, always at full quality."
                    )
                    with gr.Row():
                        unified_export_name_in = gr.Textbox(label="Export filename (no extension)", value="vibevideo_export")
                        unified_export_btn = gr.Button("Export Preview", variant="primary")
                    unified_export_file = gr.File(label="Exported file")
                    unified_export_status = gr.Markdown("")

                    gr.Markdown("### Actions")
                    instance_dropdown = gr.Dropdown(label="Target clip instance", choices=[])

                    with gr.Row():
                        clip_preview_btn = gr.Button("Preview This Clip")
                    gr.Markdown("_Shows in the Preview window above — use the shared Selection/Export controls up there to trim or export it._")

                    with gr.Row():
                        trim_in = gr.Number(label="New in (s)", value=0.0)
                        trim_out = gr.Number(label="New out (s)", value=1.0)
                        trim_btn = gr.Button("Trim")

                    with gr.Row():
                        move_row_in = gr.Number(label="Move to row")
                        move_btn = gr.Button("Move")

                    with gr.Row():
                        copy_row_in = gr.Number(
                            label="Copy to row (blank = same row, new letter)",
                            value=None,
                        )
                        copy_btn = gr.Button("Copy")

                    with gr.Row():
                        remove_btn = gr.Button("Remove")
                        undo_btn = gr.Button("Undo last action")

                    # Supporting detail for the Working Grid above, folded in here rather than
                    # shown as a separate top-level grid/list (formerly "Active List" +
                    # "Action List (history log)").
                    with gr.Accordion("Working Grid data (timeline + action log)", open=False):
                        active_df = gr.Dataframe(
                            headers=["instanceId", "label", "sourceMediaId", "inPoint", "outPoint", "row"],
                            label="Current timeline (resolved from the Working Grid)", interactive=False,
                        )
                        action_df = gr.Dataframe(
                            headers=["sequence", "type", "instanceId", "params"],
                            label="Every edit, in order — nothing here ever changes source media",
                            interactive=False,
                        )

            # [SEC:UI-ROW-PREVIEW] row_target_in kept hidden — written by row-label
            # clicks and read by refresh_working_grid throughout.
            row_target_in = gr.Number(label="Row number", value=None, visible=False)
            # [SEC:UI-GRID-PREVIEW] grid_preview_btn kept hidden — wiring removed.
            grid_preview_btn = gr.Button("Preview Entire Grid", variant="primary", visible=False)
            # [SEC:UI-CUSTOM-SELECTION] hidden bridge textboxes drive auto-preview on tick.
            custom_cell_click_bridge = gr.Textbox(elem_id="custom_cell_click_bridge", elem_classes=["vv-hidden-bridge"], value="")
            custom_row_click_bridge = gr.Textbox(elem_id="custom_row_click_bridge", elem_classes=["vv-hidden-bridge"], value="")
            custom_col_click_bridge = gr.Textbox(elem_id="custom_col_click_bridge", elem_classes=["vv-hidden-bridge"], value="")
            custom_all_click_bridge = gr.Textbox(elem_id="custom_all_click_bridge", elem_classes=["vv-hidden-bridge"], value="")
            custom_sel_status = gr.Markdown(visible=False)
            custom_sel_clear_btn = gr.Button("Clear Selection", visible=False)
            custom_sel_preview_btn = gr.Button("Preview Selection", variant="primary", visible=False)

        # TAB 2: AI Command Assistant (Integrates NLP command matching and file mappings)
        # ---------------- [SEC:UI-ASSISTANT-TAB] ----------------
        with gr.Tab("AI Command Assistant", render_children=True):
            gr.Markdown("## VibeVideo AI Natural Language Assistant")
            gr.Markdown(
                "Use VibeVideo's embedding model to run editing commands. "
                "You can reference files by their valid labels from the table below, e.g., `file1`, `f1`, `[1]`, or their original filenames — "
                "or reference a Working Grid cell directly by its `R<row>C<col>` position (e.g. `R0C1`, `R2C3`), and it will be resolved to "
                "the clip currently sitting in that cell."
            )
            
            with gr.Row():
                # Inputs Column
                with gr.Column(scale=3):
                    ai_query = gr.Textbox(
                        label="AI Editing Command",
                        placeholder="e.g. Join R0C0 and R1C0\nor trim file1 from 2 to 5 seconds as output.mp4\nor download this youtube video and turn it to mp3 https://...",
                        lines=3,
                    )
                    run_ai_btn = gr.Button("Execute AI Command", variant="primary")
                    
                    gr.Markdown("### Library File Mappings")
                    gr.Markdown("These mappings automatically resolve labels like `file1` or file names to physical filenames in the folder.")
                    file_mapping_df = gr.Dataframe(
                        headers=["Valid Names in Commands", "Actual Library File", "Type", "Duration"],
                        interactive=False,
                    )

                # Outputs Column
                with gr.Column(scale=2):
                    gr.Markdown("**Result shows in the shared Preview window on the Visual Chessboard Editor tab** — along with the shared Selection/Export controls there, so it can be trimmed or re-exported just like anything else.")
                    ai_logs = gr.Textbox(
                        label="AI Command Logs & Outputs",
                        elem_classes=["ai-logs"],
                        interactive=False,
                        lines=18,
                    )

    # ============================================================================
    # WIRING — event handlers, grouped to mirror the UI sections above.
    # Order here has no functional effect in Gradio; it's grouped purely so a
    # change to one feature only touches one clearly-labeled block.
    # ============================================================================

    def update_media_dropdown(available_list):
        choices = [f'{m["mediaId"]} | {m["filename"]}' for m in available_list]
        return gr.Dropdown(choices=choices)

    # ---------------- [SEC:WIRING-STARTUP] Startup + file upload ----------------
    # Three-step chain on page load:
    #   Step 1 — instant: show loading spinner in the library grid area
    #   Step 2 — slow:    scan sample_media/ and generate proxies (on_load_trigger)
    #   Step 3 — fast:    render the real thumbnail grid from the populated state
    demo.load(
        on_load_show_spinner,
        inputs=None,
        outputs=[library_grid_html],
    ).then(
        on_load_trigger,
        inputs=[available_state],
        outputs=[available_state, available_df, upload_status, media_dropdown, file_mapping_df],
    ).then(
        refresh_library_grid_only,
        inputs=[available_state, library_selection_state, library_sort_key, library_sort_dir, library_added_instances_state, action_state],
        outputs=[library_grid_html, media_dropdown],
    )

    file_upload.upload(
        ingest_files,
        inputs=[file_upload, available_state, default_image_duration_in],
        outputs=[available_state, available_df, upload_status],
    ).then(
        update_media_dropdown, inputs=[available_state], outputs=[media_dropdown],
    ).then(
        lambda available_list: render_mapping_df(available_list),
        inputs=[available_state],
        outputs=[file_mapping_df],
    ).then(
        refresh_library_grid_only,
        inputs=[available_state, library_selection_state, library_sort_key, library_sort_dir, library_added_instances_state, action_state],
        outputs=[library_grid_html, media_dropdown],
    )

    # ---------------- [SEC:WIRING-AI-ASSISTANT] AI Command Assistant tab ----------------
    run_ai_btn.click(
        run_ai_command,
        inputs=[ai_query, available_state, action_state],
        outputs=[available_state, available_df, ai_logs, unified_preview_video, file_mapping_df, media_dropdown],
    ).then(
        finalize_ai_output_target,
        inputs=[unified_preview_video],
        outputs=[preview_target_state, unified_sel_bar_html, unified_preview_status],
    ).then(
        refresh_library_grid_only,
        inputs=[available_state, library_selection_state, library_sort_key, library_sort_dir, library_added_instances_state, action_state],
        outputs=[library_grid_html, media_dropdown],
    )

    # ---------------- [SEC:WIRING-LIBRARY-GRID] Library Grid (thumbnail browser) ----------------
    # Decoupled 3-stage pipeline (app47 change):
    #   Stage 0 — sync_library_selection_to_grid: pure data/state update (fast, ~1ms).
    #             Updates action_state, library_selection_state, added_map etc.
    #   Stage A — fast_refresh_ui_on_library_click: instant UI refresh (~20ms, no FFmpeg).
    #             Updates library_grid_html, working_grid_html, media_dropdown,
    #             unified_preview_status ("Generating preview…"), preview_target_state,
    #             unified_sel_bar_html.  Because library_grid_html finishes in ~20ms,
    #             Gradio un-dims the Library panel almost immediately — the user can
    #             click another tile right away without any opacity lock.
    #   Stage B — render_library_preview_video_only: heavy FFmpeg render (async).
    #             Outputs ONLY unified_preview_video + unified_preview_status.
    #             library_grid_html is intentionally absent here — Gradio will
    #             never dim the Library panel during this slow FFmpeg step.
    library_click_bridge.change(
        # Combined select/deselect handler: adds the clicked tile's media to
        # the Working Grid when selected (skipping duplicates if it's
        # already there), and removes it when the same tile is deselected.
        sync_library_selection_to_grid,
        inputs=[
            library_click_bridge, library_selection_state, add_row_in, add_col_in,
            available_state, action_state, library_added_instances_state,
        ],
        outputs=[
            library_selection_state, action_state, active_df, action_df,
            instance_dropdown, library_added_instances_state,
        ],
    ).then(
        # Stage A: instant UI update — library grid checkmark, working grid clip
        # tile, dropdown, status text, selection bar all update in ~20ms.
        fast_refresh_ui_on_library_click,
        inputs=[
            available_state, library_selection_state, library_sort_key, library_sort_dir,
            library_added_instances_state, action_state,
            instance_dropdown, row_target_in, custom_selection_state,
        ],
        outputs=[
            library_grid_html, working_grid_html, media_dropdown,
            unified_preview_status, preview_target_state, unified_sel_bar_html,
        ],
    ).then(
        # Stage B: async FFmpeg preview render — only touches the preview player.
        # library_grid_html is NOT in outputs here, so Gradio will never dim
        # the Library panel while this heavy step runs.
        render_library_preview_video_only,
        inputs=[available_state, library_selection_state],
        outputs=[unified_preview_video, unified_preview_status],
    )

    library_sort_key.change(
        refresh_library_view,
        inputs=[available_state, library_selection_state, library_sort_key, library_sort_dir, library_added_instances_state, action_state],
        outputs=[library_grid_html, media_dropdown, unified_preview_video, unified_preview_status, preview_target_state, unified_sel_bar_html],
    )

    library_sort_dir.change(
        refresh_library_view,
        inputs=[available_state, library_selection_state, library_sort_key, library_sort_dir, library_added_instances_state, action_state],
        outputs=[library_grid_html, media_dropdown, unified_preview_video, unified_preview_status, preview_target_state, unified_sel_bar_html],
    )

    # ---------------- [SEC:WIRING-CHESSBOARD-ADD] Add to Grid ----------------
    add_active_btn.click(
        add_to_active,
        inputs=[media_dropdown, add_row_in, add_col_in, available_state, action_state],
        outputs=[action_state, active_df, action_df, instance_dropdown],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    )

    # ---------------- [SEC:WIRING-CHESSBOARD-AI] Chessboard AI command ----------------
    cb_run_ai_btn.click(
        run_ai_command_chessboard,
        inputs=[
            cb_ai_query, cb_ai_scope, instance_dropdown, row_target_in,
            unified_sel_box,
            cb_ai_row_in, cb_ai_col_in,
            available_state, action_state,
            custom_selection_state,
        ],
        outputs=[
            available_state, action_state,
            available_df, active_df, action_df,
            working_grid_html, instance_dropdown,
            media_dropdown, file_mapping_df,
            cb_ai_logs,
        ],
    )

    # ---------------- [SEC:WIRING-GRID-SELECTION] Clicking cells/rows on the Working Media Grid ----------------
    # Clicking a clip's body selects that clip instance and previews it.
    grid_click_bridge.change(
        select_grid_cell,
        inputs=[grid_click_bridge, action_state],
        outputs=[instance_dropdown],
    ).then(
        preview_single_clip,
        inputs=[instance_dropdown, action_state, available_state],
        outputs=[unified_preview_video, unified_preview_status],
    ).then(
        set_preview_target_clip,
        inputs=[instance_dropdown, action_state],
        outputs=[preview_target_state, unified_sel_bar_html],
    )

    # Clicking a row label selects that row (Row Preview + Chessboard AI Row
    # scope), previews it, and refreshes the shared selection bar.
    row_click_bridge.change(
        select_grid_row,
        inputs=[row_click_bridge],
        outputs=[row_target_in, cb_ai_scope],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    ).then(
        preview_row,
        inputs=[row_target_in, action_state, available_state],
        outputs=[unified_preview_video, unified_preview_status],
    ).then(
        set_preview_target_row,
        inputs=[row_target_in, action_state],
        outputs=[preview_target_state, unified_sel_bar_html],
    )

    # Keep the Grid's row highlight in sync whenever Row number changes any
    # other way (typed directly, etc.), and keep the shared selection bar
    # matching that row so a range can be typed in without re-clicking Preview.
    row_target_in.change(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    ).then(
        set_preview_target_row,
        inputs=[row_target_in, action_state],
        outputs=[preview_target_state, unified_sel_bar_html],
    )

    # Selecting a clip instance from the dropdown refreshes the shared
    # selection bar and re-highlights it on the Grid.
    instance_dropdown.change(
        set_preview_target_clip,
        inputs=[instance_dropdown, action_state],
        outputs=[preview_target_state, unified_sel_bar_html],
    )
    instance_dropdown.change(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    )

    # ---------------- [SEC:WIRING-CLIP-ACTIONS] Clip preview + trim/move/copy/remove/undo ----------------
    clip_preview_btn.click(
        preview_single_clip,
        inputs=[instance_dropdown, action_state, available_state],
        outputs=[unified_preview_video, unified_preview_status],
    ).then(
        set_preview_target_clip,
        inputs=[instance_dropdown, action_state],
        outputs=[preview_target_state, unified_sel_bar_html],
    )

    trim_btn.click(
        apply_trim,
        inputs=[instance_dropdown, trim_in, trim_out, action_state],
        outputs=[action_state, active_df, action_df],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    )

    move_btn.click(
        apply_move,
        inputs=[instance_dropdown, move_row_in, action_state],
        outputs=[action_state, active_df, action_df],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    )

    copy_btn.click(
        apply_copy,
        inputs=[instance_dropdown, copy_row_in, action_state],
        outputs=[action_state, active_df, action_df, instance_dropdown],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    )

    remove_btn.click(
        apply_remove,
        inputs=[instance_dropdown, action_state],
        outputs=[action_state, active_df, action_df, instance_dropdown],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    ).then(
        # Removing a clip here can deactivate an instance that was auto-added
        # by a Library Grid tile click — refresh the Library Grid so that
        # tile's checkmark/top-row placement clears immediately, without
        # waiting for an unrelated Library Grid refresh to happen to catch it.
        refresh_library_grid_only,
        inputs=[available_state, library_selection_state, library_sort_key, library_sort_dir, library_added_instances_state, action_state],
        outputs=[library_grid_html, media_dropdown],
    )

    undo_btn.click(
        apply_undo,
        inputs=[action_state],
        outputs=[action_state, active_df, action_df, instance_dropdown],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    ).then(
        # Same reasoning as Remove above — an Undo can deactivate an
        # instance the Library Grid still thinks is checkmarked.
        refresh_library_grid_only,
        inputs=[available_state, library_selection_state, library_sort_key, library_sort_dir, library_added_instances_state, action_state],
        outputs=[library_grid_html, media_dropdown],
    )

    # ---------------- [SEC:WIRING-GRID-MOVE] Grid arrow-move buttons + row shift ----------------
    move_up_btn.click(
        lambda choice, actions: grid_move(choice, "up", actions),
        inputs=[instance_dropdown, action_state],
        outputs=[action_state, active_df, action_df],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    )
    move_down_btn.click(
        lambda choice, actions: grid_move(choice, "down", actions),
        inputs=[instance_dropdown, action_state],
        outputs=[action_state, active_df, action_df],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    )
    move_left_btn.click(
        lambda choice, actions: grid_move(choice, "left", actions),
        inputs=[instance_dropdown, action_state],
        outputs=[action_state, active_df, action_df],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    )
    move_right_btn.click(
        lambda choice, actions: grid_move(choice, "right", actions),
        inputs=[instance_dropdown, action_state],
        outputs=[action_state, active_df, action_df],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    )

    shift_row_btn.click(
        grid_shift_row,
        inputs=[shift_row_in, shift_seconds_in, action_state],
        outputs=[action_state, active_df, action_df],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    )
    overlay_set_btn.click(
        grid_set_row_overlay,
        inputs=[overlay_row_in, overlay_scale_in, overlay_corner_in, action_state],
        outputs=[action_state, active_df, action_df, overlay_status],
    )
    zindex_set_btn.click(
        grid_set_row_zindex,
        inputs=[zindex_row_in, zindex_value_in, action_state],
        outputs=[action_state, active_df, action_df, zindex_status],
    )

    # [SEC:WIRING-ROW-PREVIEW] row_preview_btn removed (redundant — row label click covers it).
    # [SEC:WIRING-GRID-PREVIEW] grid_preview_btn removed (redundant — top-left tick covers it).

    # ---------------- [SEC:WIRING-CUSTOM-SELECTION] Custom Selection (any combination) ----------------
    # Clicking a clip's +/✓ badge toggles it; clicking a row/column header's
    # own toggle toggles every clip in that row/column; the top-left corner
    # toggle selects/deselects everything. All five converge on the same
    # refresh so the Working Media Grid + status text always reflect the
    # current custom_selection_state, and automatically update the shared
    # Preview screen + Selection system to match.
    custom_cell_click_bridge.change(
        toggle_custom_selection_cell,
        inputs=[custom_cell_click_bridge, custom_selection_state],
        outputs=[custom_selection_state],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    ).then(
        refresh_custom_selection_status,
        inputs=[action_state, custom_selection_state],
        outputs=[custom_sel_status],
    ).then(
        preview_custom_selection,
        inputs=[action_state, available_state, custom_selection_state],
        outputs=[unified_preview_video, unified_preview_status],
    ).then(
        set_preview_target_custom,
        inputs=[action_state, custom_selection_state],
        outputs=[preview_target_state, unified_sel_bar_html],
    ).then(
        auto_scope_from_selection,
        inputs=[custom_selection_state],
        outputs=[cb_ai_scope],
    )

    custom_row_click_bridge.change(
        toggle_custom_selection_row,
        inputs=[custom_row_click_bridge, action_state, custom_selection_state],
        outputs=[custom_selection_state],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    ).then(
        refresh_custom_selection_status,
        inputs=[action_state, custom_selection_state],
        outputs=[custom_sel_status],
    ).then(
        preview_custom_selection,
        inputs=[action_state, available_state, custom_selection_state],
        outputs=[unified_preview_video, unified_preview_status],
    ).then(
        set_preview_target_custom,
        inputs=[action_state, custom_selection_state],
        outputs=[preview_target_state, unified_sel_bar_html],
    ).then(
        auto_scope_from_selection,
        inputs=[custom_selection_state],
        outputs=[cb_ai_scope],
    )

    custom_col_click_bridge.change(
        toggle_custom_selection_col,
        inputs=[custom_col_click_bridge, action_state, custom_selection_state],
        outputs=[custom_selection_state],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    ).then(
        refresh_custom_selection_status,
        inputs=[action_state, custom_selection_state],
        outputs=[custom_sel_status],
    ).then(
        preview_custom_selection,
        inputs=[action_state, available_state, custom_selection_state],
        outputs=[unified_preview_video, unified_preview_status],
    ).then(
        set_preview_target_custom,
        inputs=[action_state, custom_selection_state],
        outputs=[preview_target_state, unified_sel_bar_html],
    ).then(
        auto_scope_from_selection,
        inputs=[custom_selection_state],
        outputs=[cb_ai_scope],
    )

    custom_all_click_bridge.change(
        toggle_custom_selection_all,
        inputs=[custom_all_click_bridge, action_state, custom_selection_state],
        outputs=[custom_selection_state],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    ).then(
        refresh_custom_selection_status,
        inputs=[action_state, custom_selection_state],
        outputs=[custom_sel_status],
    ).then(
        preview_custom_selection,
        inputs=[action_state, available_state, custom_selection_state],
        outputs=[unified_preview_video, unified_preview_status],
    ).then(
        set_preview_target_custom,
        inputs=[action_state, custom_selection_state],
        outputs=[preview_target_state, unified_sel_bar_html],
    ).then(
        auto_scope_from_selection,
        inputs=[custom_selection_state],
        outputs=[cb_ai_scope],
    )

    custom_sel_clear_btn.click(
        clear_custom_selection,
        outputs=[custom_selection_state],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    ).then(
        refresh_custom_selection_status,
        inputs=[action_state, custom_selection_state],
        outputs=[custom_sel_status],
    ).then(
        preview_custom_selection,
        inputs=[action_state, available_state, custom_selection_state],
        outputs=[unified_preview_video, unified_preview_status],
    ).then(
        set_preview_target_custom,
        inputs=[action_state, custom_selection_state],
        outputs=[preview_target_state, unified_sel_bar_html],
    ).then(
        auto_scope_from_selection,
        inputs=[custom_selection_state],
        outputs=[cb_ai_scope],
    )

    # custom_sel_preview_btn removed — auto-preview fires on every badge/header tick above.

    # ---------------- [SEC:WIRING-UNIFIED-SELECTION-EXPORT] The ONE Selection
    # system + ONE Export button, multiplexing every preview kind above ----------------
    unified_sel_preview_btn.click(
        preview_unified_selection,
        inputs=[unified_sel_box, preview_target_state, action_state, available_state],
        outputs=[unified_preview_video, unified_preview_status],
    )

    unified_sel_clear_btn.click(lambda: "", outputs=[unified_sel_box])

    unified_export_btn.click(
        export_unified_preview,
        inputs=[unified_sel_box, preview_target_state, action_state, available_state, unified_export_name_in],
        outputs=[unified_export_file, unified_export_status],
    )

    # ---------------- [SEC:WIRING-CLIP-OVERLAY] Clip Overlay & Preview Download wiring ----------------
    clip_overlay_set_btn.click(
        grid_set_clip_overlay,
        inputs=[instance_dropdown, clip_overlay_mode, clip_overlay_scale, clip_overlay_corner, action_state],
        outputs=[action_state, active_df, action_df, clip_overlay_status],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    )

    clip_overlay_reset_btn.click(
        grid_reset_clip_overlay,
        inputs=[instance_dropdown, action_state],
        outputs=[action_state, active_df, action_df, clip_overlay_status],
    ).then(
        refresh_working_grid,
        inputs=[action_state, instance_dropdown, row_target_in, custom_selection_state],
        outputs=[working_grid_html],
    )

    # Synchronize clip overlay UI inputs when a clip is selected
    instance_dropdown.change(
        get_clip_overlay_ui_values,
        inputs=[instance_dropdown, action_state],
        outputs=[clip_overlay_mode, clip_overlay_corner, clip_overlay_scale],
    )


if __name__ == "__main__":
    demo.queue().launch(share=True, css=CUSTOM_CSS)
