"""
Headless Blender — Single-Video Focus-Point Zoom Tester (Fixed 16:9 Canvas)
=============================================================================

Standalone, minimal script for testing the "zoom into one exact part of
the frame" behavior on ONE video, isolated from the split-screen setup.
Once you've dialed in focus_x / focus_y / extra_zoom here, those same
values drop straight into ZOOM_RANGES in the split-screen script — this
uses the identical math.

CANVAS IS FIXED 16:9 (1920x1080 by default), REGARDLESS OF SOURCE ASPECT
RATIO:
  - Normal (non-zoomed) state: the video is placed with a "contain" fit
    — scaled down (or up) so the WHOLE frame is visible inside the
    canvas, centered. If the video's aspect ratio doesn't match 16:9,
    you'll see black bars (letterbox/pillarbox) — this is expected.
  - Zoomed state: the video is scaled with a "cover" fit — enough to
    completely fill the canvas with no black bars — and then further
    zoomed in by your `zoom_factor` on top of that, panned to your
    focus point.

EDGE-CLIP PROTECTION
---------------------
When you zoom into a focus point near a corner/edge of the frame, naively
panning to center that point can push the video past its own edge,
exposing black beyond the real footage. This script clamps the pan
offset on each axis to the maximum distance the video can move while
still fully covering the canvas. If your requested focus point would
need more room than that, it pans as close as it safely can instead of
overshooting into black.

HOW TO SET A ZOOM WINDOW
--------------------------
Edit ZOOM_RANGES below. Each entry:

    (start_seconds, end_seconds, focus_x, focus_y, zoom_factor)

- focus_x / focus_y: fraction (0.0-1.0) of the SOURCE frame to keep
  centered once zoomed in. (0,0)=top-left, (0.5,0.5)=center,
  (1,1)=bottom-right.
- zoom_factor: how far to zoom in BEYOND the "cover" fill scale, e.g.
  1.6 = 60% closer than the fully-filled canvas. Must be >= 1.0 or you
  won't see any extra zoom (1.0 = exactly filling the canvas, no more).

    ZOOM_RANGES = [
        (2.0, 5.0, 0.25, 0.3, 1.6),   # zoom into upper-left-ish area
    ]

You can also omit focus_x/focus_y/zoom_factor:
    (start, end)                          -> center focus, zoom_factor 1.5
    (start, end, focus_x, focus_y)        -> zoom_factor defaults to 1.5

STAYING ZOOMED IN (no zoom-out)
---------------------------------
Add a 6th item, `hold=True`, to keep the zoom punched in for the rest of
the render instead of easing back out at `end_seconds`:

    (start_seconds, end_seconds, focus_x, focus_y, zoom_factor, True)

With `hold=True`, `end_seconds` is only used as a safeguard against
overlapping with a later ZOOM_RANGES entry — the actual "return to
normal" keyframe is skipped entirely, so the shot just stays zoomed in
on focus_x/focus_y all the way to the end of the video.

TRACKING A MOVING SUBJECT (TRACKED_ZOOMS)
--------------------------------------------
A single focus_x/focus_y only works if the subject holds still. For a
subject that moves, use TRACKED_ZOOMS instead: point it at a CSV
produced by coordinate_picker.py (time_seconds, focus_x, focus_y rows —
click the subject every ~0.5s as it moves). The pan will follow the
subject by linearly interpolating between your clicked points, easing
in from the normal state at the first point and, if hold=True, staying
on the last tracked position for the rest of the render.

    TRACKED_ZOOMS = [
        {"csv_path": r"C:\path\to\focus_track.csv", "zoom_factor": 1.6, "hold": True},
    ]

RUN (fully headless, no window):
    blender --background --python zoom_single_video_test.py
"""

import bpy
import csv
import os

# ---------------------------------------------------------------------------
# CONFIG — edit path and zoom window(s) here
# ---------------------------------------------------------------------------
VIDEO_PATH = r"C:\Users\saket\Documents\Manim\satoshi_edits_video.mp4"

FPS = 30

# Fixed output canvas. Change these if you want a different resolution,
# just keep the 16:9 ratio (or don't — the math works for any ratio).
CANVAS_WIDTH = 1920
CANVAS_HEIGHT = 1080

# Ease-in / ease-out duration for the zoom transition.
ZOOM_FADE_SECONDS = 0.5

# Default zoom_factor used when an entry omits it (applied ON TOP of the
# "cover" fill scale — see docstring above).
DEFAULT_ZOOM_FACTOR = 1.5

# ---- EDIT THIS: zoom window(s) ----
# (start_seconds, end_seconds, focus_x, focus_y, zoom_factor, hold)
# hold=True means it eases into the zoom at start_seconds and STAYS
# zoomed for the rest of the video (end_seconds is ignored for the
# return-to-normal step in that case).
ZOOM_RANGES = [
    # (2.0, 5.0, 0.22, 0.40, 1.6, True),  # disabled: superseded by TRACKED_ZOOMS below
]

# ---- Moving-subject tracking (from coordinate_picker.py's CSV) ----
# Each entry pans through the recorded track instead of holding one
# fixed point. zoom_factor works the same as above (multiplier on top
# of "cover" fill scale). hold=True keeps the last tracked framing for
# the rest of the render; hold=False eases back out to normal after the
# last point.
TRACKED_ZOOMS = [
    {
        "csv_path": r"C:\Users\saket\Documents\Manim\focus_track.csv",
        "zoom_factor": 1.6,
        "hold": True,
    },
]

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "zoom_test_output.mp4"
)


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def seconds_to_frame(seconds, fps):
    """Convert a timeline position in seconds to a frame number (frame 1 = 0.0s)."""
    return round(seconds * fps) + 1


def compute_fit_scales(src_w, src_h, canvas_w, canvas_h):
    """Return (contain_scale, cover_scale) for fitting a src_w x src_h
    image into a canvas_w x canvas_h canvas.

    contain_scale: the LARGEST scale at which the whole source frame
        still fits entirely inside the canvas (may letterbox/pillarbox).
    cover_scale: the SMALLEST scale at which the source frame completely
        fills the canvas with no gaps (may crop the source frame).
    """
    contain_scale = min(canvas_w / src_w, canvas_h / src_h)
    cover_scale = max(canvas_w / src_w, canvas_h / src_h)
    return contain_scale, cover_scale


def compute_focus_offset(focus_x, focus_y, source_width, source_height, scale):
    """Given a focus point in the SOURCE frame (0-1 fractions, (0,0) =
    top-left, (1,1) = bottom-right) and the scale the source is being
    displayed at, return the (offset_x, offset_y) needed so that focus
    point lands at the canvas center instead of the default frame-center.

    Blender VSE strip transform convention: offset_x positive moves the
    image right, offset_y positive moves the image up. A focus point to
    the right of / below center therefore needs a negative x / positive y
    shift to be pulled back to the middle of the canvas.
    """
    offset_x = -(focus_x - 0.5) * source_width * scale
    offset_y = (focus_y - 0.5) * source_height * scale
    return offset_x, offset_y


def clamp_offset_to_cover(offset_x, offset_y, source_width, source_height,
                           scale, canvas_w, canvas_h):
    """Clamp a pan offset so the scaled source (at `scale`) never moves
    far enough to expose its own edge — i.e. it always fully covers the
    canvas. This is what fixes the "black sliver at the edge" issue when
    zooming into a focus point near a corner.
    """
    render_w = source_width * scale
    render_h = source_height * scale

    # How far the video CAN move on each axis before its edge would be
    # dragged inside the canvas bounds. If the video is exactly canvas
    # sized on an axis (no slack), max offset on that axis is 0.
    max_offset_x = max(0.0, (render_w - canvas_w) / 2.0)
    max_offset_y = max(0.0, (render_h - canvas_h) / 2.0)

    clamped_x = max(-max_offset_x, min(max_offset_x, offset_x))
    clamped_y = max(-max_offset_y, min(max_offset_y, offset_y))
    return clamped_x, clamped_y


def load_focus_track_csv(path):
    """Load a (time_seconds, focus_x, focus_y) track written by
    coordinate_picker.py. Returns a list of (float, float, float)
    tuples sorted by time.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Track CSV not found: {path}\n"
            f"Record one with coordinate_picker.py first."
        )
    track = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            track.append((
                float(row["time_seconds"]),
                float(row["focus_x"]),
                float(row["focus_y"]),
            ))
    track.sort(key=lambda p: p[0])
    if not track:
        raise ValueError(f"Track CSV has no rows: {path}")
    return track


def _parse_zoom_entry(entry):
    """Accept entries of varying length:
        (start, end)                                        -> center focus, default zoom, no hold
        (start, end, focus_x, focus_y)                      -> default zoom_factor, no hold
        (start, end, focus_x, focus_y, zoom_factor)         -> no hold
        (start, end, focus_x, focus_y, zoom_factor, hold)   -> hold=True stays zoomed to the end
    """
    if len(entry) == 2:
        start, end = entry
        return start, end, 0.5, 0.5, DEFAULT_ZOOM_FACTOR, False
    if len(entry) == 4:
        start, end, focus_x, focus_y = entry
        return start, end, focus_x, focus_y, DEFAULT_ZOOM_FACTOR, False
    if len(entry) == 5:
        return entry + (False,)
    if len(entry) == 6:
        return entry
    raise ValueError(
        f"ZOOM_RANGES entry must have 2, 4, 5, or 6 items, got {len(entry)}: {entry}"
    )


def animate_zoom(strip, source_width, source_height, contain_scale, cover_scale,
                  canvas_w, canvas_h, start_frame, end_frame, fade_frames,
                  focus_x, focus_y, zoom_factor, hold=False):
    """Scale/pan `strip` from its normal "contain" state (whole frame
    visible, centered) up to a "cover + zoom_factor" state (canvas fully
    filled, then punched in further) while re-centering on
    (focus_x, focus_y). Eased Bezier keyframes for a smooth "punch in".
    Pan is clamped so the video's real edge is never exposed.

    If hold is False (default): holds the zoom until end_frame, then
    eases back out to normal — the original pulse-zoom behavior.
    If hold is True: eases into the zoom and then STOPS — no return
    keyframe is written, so Blender's constant extrapolation holds the
    zoomed-in framing for the rest of the render.
    """
    orig_scale = contain_scale
    orig_offset_x, orig_offset_y = 0.0, 0.0

    target_scale = cover_scale * zoom_factor
    raw_offset_x, raw_offset_y = compute_focus_offset(
        focus_x, focus_y, source_width, source_height, target_scale
    )
    target_offset_x, target_offset_y = clamp_offset_to_cover(
        raw_offset_x, raw_offset_y, source_width, source_height,
        target_scale, canvas_w, canvas_h,
    )

    duration = end_frame - start_frame
    fade = min(fade_frames, duration // 2) if duration > 0 else 0

    if hold:
        # Ease in, then stop writing keyframes entirely. Blender's default
        # constant extrapolation holds the last keyframe's value forever,
        # so the shot stays zoomed in from here to the end of the render.
        keyframe_points = [
            (start_frame, orig_scale, orig_scale, orig_offset_x, orig_offset_y),
            (start_frame + fade, target_scale, target_scale, target_offset_x, target_offset_y),
        ]
    else:
        keyframe_points = [
            (start_frame, orig_scale, orig_scale, orig_offset_x, orig_offset_y),
            (start_frame + fade, target_scale, target_scale, target_offset_x, target_offset_y),
            (end_frame - fade, target_scale, target_scale, target_offset_x, target_offset_y),
            (end_frame, orig_scale, orig_scale, orig_offset_x, orig_offset_y),
        ]

    prev_interp = bpy.context.preferences.edit.keyframe_new_interpolation_type
    bpy.context.preferences.edit.keyframe_new_interpolation_type = 'BEZIER'
    try:
        transform = strip.transform
        for frame, sx, sy, ox, oy in keyframe_points:
            transform.scale_x = sx
            transform.scale_y = sy
            transform.offset_x = ox
            transform.offset_y = oy
            transform.keyframe_insert(data_path="scale_x", frame=frame)
            transform.keyframe_insert(data_path="scale_y", frame=frame)
            transform.keyframe_insert(data_path="offset_x", frame=frame)
            transform.keyframe_insert(data_path="offset_y", frame=frame)
    finally:
        bpy.context.preferences.edit.keyframe_new_interpolation_type = prev_interp


def animate_tracked_zoom(strip, source_width, source_height, contain_scale, cover_scale,
                          canvas_w, canvas_h, track_points, fps, fade_frames,
                          zoom_factor, hold=True):
    """Like animate_zoom, but pans through a whole TRACK of
    (time_seconds, focus_x, focus_y) points (as loaded from
    coordinate_picker.py's CSV) instead of holding one static focus
    point. Eases in from the normal "contain" state to the first track
    point, then pans LINEARLY between each subsequent point at a
    constant zoom (cover_scale * zoom_factor) — linear because the
    track points are evenly spaced clicks, so constant velocity between
    them tracks the recorded motion most faithfully. Every point is
    clamped so the video's real edge is never exposed.

    hold=True: stays on the last tracked position/zoom for the rest of
    the render (no return to normal).
    hold=False: eases back out to normal after the last track point.
    """
    target_scale = cover_scale * zoom_factor

    def clamped_offset(focus_x, focus_y):
        raw_x, raw_y = compute_focus_offset(
            focus_x, focus_y, source_width, source_height, target_scale
        )
        return clamp_offset_to_cover(
            raw_x, raw_y, source_width, source_height,
            target_scale, canvas_w, canvas_h,
        )

    transform = strip.transform
    prev_interp = bpy.context.preferences.edit.keyframe_new_interpolation_type

    def insert_kf(frame, scale, offset_x, offset_y, interp):
        bpy.context.preferences.edit.keyframe_new_interpolation_type = interp
        transform.scale_x = scale
        transform.scale_y = scale
        transform.offset_x = offset_x
        transform.offset_y = offset_y
        transform.keyframe_insert(data_path="scale_x", frame=frame)
        transform.keyframe_insert(data_path="scale_y", frame=frame)
        transform.keyframe_insert(data_path="offset_x", frame=frame)
        transform.keyframe_insert(data_path="offset_y", frame=frame)

    try:
        first_t, first_fx, first_fy = track_points[0]
        first_frame = seconds_to_frame(first_t, fps)
        first_offset_x, first_offset_y = clamped_offset(first_fx, first_fy)

        # Ease in from normal to the first tracked point.
        fade_in_start = max(1, first_frame - fade_frames)
        insert_kf(fade_in_start, contain_scale, 0.0, 0.0, 'BEZIER')
        insert_kf(first_frame, target_scale, first_offset_x, first_offset_y, 'LINEAR')

        # Pan through the rest of the track at constant zoom.
        last_frame = first_frame
        last_fx, last_fy = first_fx, first_fy
        for t, fx, fy in track_points[1:]:
            frame = seconds_to_frame(t, fps)
            if frame <= last_frame:
                continue  # skip out-of-order/duplicate timestamps
            offset_x, offset_y = clamped_offset(fx, fy)
            insert_kf(frame, target_scale, offset_x, offset_y, 'LINEAR')
            last_frame = frame
            last_fx, last_fy = fx, fy

        if not hold:
            # Re-touch the last track keyframe so its OUTGOING segment
            # (into the fade-out) eases with Bezier instead of linear,
            # then ease back to normal.
            last_offset_x, last_offset_y = clamped_offset(last_fx, last_fy)
            insert_kf(last_frame, target_scale, last_offset_x, last_offset_y, 'BEZIER')
            fade_out_end = last_frame + fade_frames
            insert_kf(fade_out_end, contain_scale, 0.0, 0.0, 'BEZIER')
    finally:
        bpy.context.preferences.edit.keyframe_new_interpolation_type = prev_interp


# ---------------------------------------------------------------------------
# BUILD THE VSE SEQUENCE
# ---------------------------------------------------------------------------
def main():
    if not os.path.isfile(VIDEO_PATH):
        raise FileNotFoundError(
            f"Video file not found: {VIDEO_PATH}\n"
            f"Update VIDEO_PATH at the top of this script."
        )

    scene = bpy.context.scene

    if scene.sequence_editor is None:
        scene.sequence_editor_create()
    seq_editor = scene.sequence_editor
    seq = seq_editor.strips if hasattr(seq_editor, "strips") else seq_editor.sequences

    for strip in list(seq):
        seq.remove(strip)

    strip = seq.new_movie(name="Video", filepath=VIDEO_PATH, channel=1, frame_start=1)
    elem = strip.elements[0]
    src_w, src_h = elem.orig_width, elem.orig_height

    # Canvas is now FIXED, independent of the source video's resolution.
    scene.render.resolution_x = CANVAS_WIDTH
    scene.render.resolution_y = CANVAS_HEIGHT
    scene.render.resolution_percentage = 100
    scene.render.fps = FPS

    contain_scale, cover_scale = compute_fit_scales(
        src_w, src_h, CANVAS_WIDTH, CANVAS_HEIGHT
    )

    # Normal (non-zoomed) state: whole frame visible, centered. Will
    # letterbox/pillarbox if the source aspect ratio isn't 16:9.
    strip.transform.scale_x = contain_scale
    strip.transform.scale_y = contain_scale
    strip.transform.offset_x = 0
    strip.transform.offset_y = 0
    strip.blend_type = 'ALPHA_OVER'
    strip.blend_alpha = 1.0

    total_frames = strip.frame_final_duration
    scene.frame_start = 1
    scene.frame_end = total_frames

    bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'
    zoom_fade_frames = round(ZOOM_FADE_SECONDS * FPS)

    for entry in ZOOM_RANGES:
        start_seconds, end_seconds, focus_x, focus_y, zoom_factor, hold = _parse_zoom_entry(entry)
        start_frame = seconds_to_frame(start_seconds, FPS)
        end_frame = seconds_to_frame(end_seconds, FPS)
        animate_zoom(
            strip, src_w, src_h, contain_scale, cover_scale,
            CANVAS_WIDTH, CANVAS_HEIGHT, start_frame, end_frame,
            zoom_fade_frames, focus_x, focus_y, zoom_factor, hold=hold,
        )

    for tracked in TRACKED_ZOOMS:
        track_points = load_focus_track_csv(tracked["csv_path"])
        animate_tracked_zoom(
            strip, src_w, src_h, contain_scale, cover_scale,
            CANVAS_WIDTH, CANVAS_HEIGHT, track_points, FPS, zoom_fade_frames,
            tracked.get("zoom_factor", DEFAULT_ZOOM_FACTOR),
            hold=tracked.get("hold", True),
        )
        print(f"Tracked zoom: {len(track_points)} points from {tracked['csv_path']}")

    scene.render.filepath = OUTPUT_PATH
    scene.render.image_settings.media_type = 'VIDEO'
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'
    scene.render.ffmpeg.constant_rate_factor = 'HIGH'

    print(f"Video: {VIDEO_PATH} ({src_w}x{src_h})")
    print(f"Canvas: {CANVAS_WIDTH}x{CANVAS_HEIGHT}")
    print(f"contain_scale={contain_scale:.4f}  cover_scale={cover_scale:.4f}")
    print(f"Zoom windows (seconds, focus_x, focus_y, zoom_factor): {ZOOM_RANGES}")
    print(f"Timeline: frame 1 to {total_frames} @ {FPS}fps")
    print(f"Output will be written to: {OUTPUT_PATH}")

    return scene


scene = main()

# ---------------------------------------------------------------------------
# Render immediately (fully headless):
#   blender --background --python zoom_single_video_test.py
# ---------------------------------------------------------------------------
bpy.ops.render.render(animation=True)
print(f"Render complete. Video saved to: {OUTPUT_PATH}")
