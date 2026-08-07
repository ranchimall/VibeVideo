"""
Headless Blender — Single-Video Focus-Point Zoom Tester
=========================================================

Standalone, minimal script for testing the "zoom into one exact part of
the frame" behavior on ONE video, isolated from the split-screen setup.
Once you've dialed in focus_x / focus_y / extra_zoom here, those same
values drop straight into ZOOM_RANGES in the split-screen script — this
uses the identical math.

WORKS WITH ANY SOURCE ASPECT RATIO: the canvas is auto-set to the
video's own native resolution (no letterboxing/cropping in the
"normal", non-zoomed state — you see the whole original frame).
Zooming in then crops into it.

HOW TO SET A ZOOM WINDOW
--------------------------
Edit ZOOM_RANGES below. Each entry:

    (start_seconds, end_seconds, focus_x, focus_y, zoom_factor)

- focus_x / focus_y: fraction (0.0-1.0) of the SOURCE frame to keep
  centered once zoomed in. (0,0)=top-left, (0.5,0.5)=center,
  (1,1)=bottom-right.
- zoom_factor: how far to zoom in, e.g. 1.5 = 50% closer. Must be > 1.0
  or you won't see any zoom (the base/unzoomed state is already scale 1
  = the full native frame, since canvas == source resolution here).

    ZOOM_RANGES = [
        (2.0, 5.0, 0.25, 0.3, 1.6),   # zoom into upper-left-ish area
    ]

You can also omit focus_x/focus_y/zoom_factor:
    (start, end)                          -> center focus, zoom_factor 1.5
    (start, end, focus_x, focus_y)        -> zoom_factor defaults to 1.5

RUN (fully headless, no window):
    blender --background --python zoom_single_video_test.py
"""

import bpy
import os

# ---------------------------------------------------------------------------
# CONFIG — edit path and zoom window(s) here
# ---------------------------------------------------------------------------
VIDEO_PATH = r"C:\Users\saket\Documents\Manim\Entropy_teaser_video.mp4"

FPS = 30

# Ease-in / ease-out duration for the zoom transition.
ZOOM_FADE_SECONDS = 0.5

# Default zoom_factor used when an entry omits it.
DEFAULT_ZOOM_FACTOR = 1.5

# ---- EDIT THIS: zoom window(s) ----
# (start_seconds, end_seconds, focus_x, focus_y, zoom_factor)
ZOOM_RANGES = [
    (2.0, 5.0, 0.25, 0.3, 1.6),
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


def _parse_zoom_entry(entry):
    """Accept entries of varying length:
        (start, end)                            -> center focus, default zoom
        (start, end, focus_x, focus_y)          -> default zoom_factor
        (start, end, focus_x, focus_y, zoom_factor)
    """
    if len(entry) == 2:
        start, end = entry
        return start, end, 0.5, 0.5, DEFAULT_ZOOM_FACTOR
    if len(entry) == 4:
        start, end, focus_x, focus_y = entry
        return start, end, focus_x, focus_y, DEFAULT_ZOOM_FACTOR
    if len(entry) == 5:
        return entry
    raise ValueError(
        f"ZOOM_RANGES entry must have 2, 4, or 5 items, got {len(entry)}: {entry}"
    )


def animate_zoom(strip, source_width, source_height, start_frame, end_frame,
                  fade_frames, focus_x, focus_y, zoom_factor):
    """Scale/pan `strip` from its normal (scale=1, offset=0,0) state up to
    zoom_factor while re-centering on (focus_x, focus_y), hold, then
    return to normal. Eased Bezier keyframes for a smooth "punch in"."""
    orig_scale = 1.0
    orig_offset_x, orig_offset_y = 0.0, 0.0

    target_scale = zoom_factor
    target_offset_x, target_offset_y = compute_focus_offset(
        focus_x, focus_y, source_width, source_height, target_scale
    )

    duration = end_frame - start_frame
    fade = min(fade_frames, duration // 2) if duration > 0 else 0

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

    # Canvas = source's own native resolution, so the un-zoomed state
    # shows the whole original frame untouched, regardless of aspect ratio.
    scene.render.resolution_x = src_w
    scene.render.resolution_y = src_h
    scene.render.resolution_percentage = 100
    scene.render.fps = FPS

    strip.transform.scale_x = 1.0
    strip.transform.scale_y = 1.0
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
        start_seconds, end_seconds, focus_x, focus_y, zoom_factor = _parse_zoom_entry(entry)
        start_frame = seconds_to_frame(start_seconds, FPS)
        end_frame = seconds_to_frame(end_seconds, FPS)
        animate_zoom(
            strip, src_w, src_h, start_frame, end_frame, zoom_fade_frames,
            focus_x, focus_y, zoom_factor,
        )

    scene.render.filepath = OUTPUT_PATH
    scene.render.image_settings.media_type = 'VIDEO'
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'
    scene.render.ffmpeg.constant_rate_factor = 'HIGH'

    print(f"Video: {VIDEO_PATH} ({src_w}x{src_h})")
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
