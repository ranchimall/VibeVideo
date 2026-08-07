"""
Headless Blender — Side-by-Side Video Combiner
WITH Manual On/Off Switching AND Position-Shift ("Travel") Animation
=============================================================================

Same layout as before (left 608x1080 / right 1312x1080 -> 1920x1080).

TWO INDEPENDENT FEATURES — use either, or both together:

1) SWITCH_OFF_RANGES  (unchanged from before)
   A side goes solid black for a time window, in the exact same spot.
   Fades in/out over FADE_SECONDS.

2) REPOSITION_RANGES  (NEW)
   A side's video SLIDES (travels) from its normal split-screen position
   to a target offset, holds there, then slides back. Size (scale) is
   NOT changed — this is a pure position move, same panel size, per your
   request. It eases in/out (smooth acceleration/deceleration) instead of
   moving at constant speed, so it reads as a "travel" rather than a snap.

   This is completely independent of SWITCH_OFF_RANGES: it always
   animates a side's OWN strip. If you want "left slides to center while
   right is off", just set matching/overlapping time windows in both
   dicts — SWITCH_OFF_RANGES["right"] and REPOSITION_RANGES["left"].

HOW TO SET SWITCH-OFF WINDOWS
------------------------------
Edit SWITCH_OFF_RANGES. Each entry is (start_seconds, end_seconds),
inclusive, during which that side goes black.

    SWITCH_OFF_RANGES = {
        "left":  [(1.5, 3.0)],
        "right": [(5.0, 7.5)],
    }

HOW TO SET REPOSITION (SHIFT/TRAVEL) WINDOWS
-----------------------------------------------
Edit REPOSITION_RANGES. Each entry is
    (start_seconds, end_seconds, target_offset_x, target_offset_y)
during which that side's video travels from its normal panel position to
(target_offset_x, target_offset_y), holds, then travels back.

offset_x / offset_y are in the same coordinate system Blender's VSE
transform already uses: (0, 0) is dead-center of the 1920x1080 canvas.
Positive offset_x moves right, positive offset_y moves up.

    REPOSITION_RANGES = {
        "left": [
            (7.0, 9.0, 0, 0),   # left video slides to dead-center
        ],
        "right": [],
    }

Leave a list empty ([]) if that side should never move / never switch off.

RUN (fully headless, no window):
    blender --background --python combine_split_screen_with_switches_and_shift.py
"""

import bpy
import os

# ---------------------------------------------------------------------------
# CONFIG — edit paths, switch-off windows, and reposition windows here
# ---------------------------------------------------------------------------
LEFT_VIDEO_PATH = r"C:\Users\saket\Documents\Manim\teaser2.mp4"
RIGHT_VIDEO_PATH = r"C:\Users\saket\Documents\Manim\media\videos\cubes_collide_and_multiply\1080p30\CubesCollideAndMultiply.mp4"

LEFT_WIDTH = 608
RIGHT_WIDTH = 1312
HEIGHT = 1080
TOTAL_WIDTH = LEFT_WIDTH + RIGHT_WIDTH  # 1920

FPS = 30

# Fade-to-black / fade-back-to-video duration for switch-off windows.
FADE_SECONDS = 0.4

# Ease-in / ease-out duration for reposition (travel) windows. Kept
# separate from FADE_SECONDS since they're independent features and you
# may want the slide to happen faster/slower than a black fade.
REPOSITION_FADE_SECONDS = 0.5

# ---- EDIT THIS: black-out windows, per side ----
SWITCH_OFF_RANGES = {
    "left": [
        (3, 6),
    ],
    "right": [
        (7.0, 9.0),
    ],
}

# ---- EDIT THIS: reposition ("travel") windows, per side ----
# (start_seconds, end_seconds, target_offset_x, target_offset_y)
REPOSITION_RANGES = {
    "left": [
        (7.0, 9.0, 0, 0),  # while right is off (see above), left slides to center
    ],
    "right": [],
}

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "final_split_screen_with_switches_and_shift.mp4"
)


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def apply_cover_fit(strip, target_width, target_height, source_width, source_height):
    """Uniformly scale a strip so it fully fills a target_width x target_height
    box (cropping any overflow) instead of leaving letterbox gaps when the
    source's native resolution doesn't match the panel exactly."""
    scale = max(target_width / source_width, target_height / source_height)
    strip.transform.scale_x = scale
    strip.transform.scale_y = scale


def seconds_to_frame(seconds, fps):
    """Convert a timeline position in seconds to a frame number (frame 1 = 0.0s)."""
    return round(seconds * fps) + 1


def create_black_png(width, height, path):
    """Render and save a solid black opaque PNG of the given size."""
    img = bpy.data.images.new("TempBlackCover", width=width, height=height, alpha=False)
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)


def add_black_cover(seq, name, channel, start_frame, end_frame, target_width, offset_x, fade_frames, tmp_dir):
    """Add a solid black strip exactly covering one panel, for frames
    [start_frame, end_frame] inclusive, fading in/out at its edges instead
    of switching instantly.

    NOTE: we deliberately use an IMAGE strip (a real black PNG sized to the
    panel) instead of a generator 'COLOR' effect strip. Blender 5.2's VSE
    has a known bug where full-canvas generator strips combined with
    transform.offset silently fail to composite. Image/movie strips don't
    have this problem, so we reuse that proven path here.
    """
    png_path = os.path.join(tmp_dir, f"{name}.png")
    create_black_png(target_width, HEIGHT, png_path)

    black = seq.new_image(
        name=name, filepath=png_path, channel=channel, frame_start=start_frame,
    )
    black.frame_final_duration = (end_frame - start_frame + 1)

    black.transform.offset_x = offset_x
    black.transform.offset_y = 0
    black.blend_type = 'ALPHA_OVER'

    duration = end_frame - start_frame
    fade = min(fade_frames, duration // 2) if duration > 0 else 0

    black.blend_alpha = 0.0
    black.keyframe_insert(data_path="blend_alpha", frame=start_frame)
    black.blend_alpha = 1.0
    black.keyframe_insert(data_path="blend_alpha", frame=start_frame + fade)
    black.blend_alpha = 1.0
    black.keyframe_insert(data_path="blend_alpha", frame=end_frame - fade)
    black.blend_alpha = 0.0
    black.keyframe_insert(data_path="blend_alpha", frame=end_frame)

    return black


def animate_reposition(scene, strip, original_offset_x, original_offset_y,
                        target_offset_x, target_offset_y,
                        start_frame, end_frame, fade_frames):
    """Make `strip` travel from its normal position to
    (target_offset_x, target_offset_y), hold, then travel back — timed
    independently of any switch-off/black-cover animation. Size/scale is
    left untouched (position-only move).

    Uses Bezier keyframes (auto handles) for this strip's move, which
    naturally eases in/out — smooth accelerate-then-decelerate — instead
    of the constant-speed Linear interpolation used for the black-cover
    fades. We flip the global "new keyframe" interpolation setting around
    just this insertion instead of reaching into Action/F-Curve internals
    directly, since Blender 5.x's layered-action data model changed that
    API (Action no longer exposes a flat .fcurves collection) and this
    preference-based approach stays stable across versions.
    """
    duration = end_frame - start_frame
    fade = min(fade_frames, duration // 2) if duration > 0 else 0

    keyframe_points = [
        (start_frame, original_offset_x, original_offset_y),
        (start_frame + fade, target_offset_x, target_offset_y),
        (end_frame - fade, target_offset_x, target_offset_y),
        (end_frame, original_offset_x, original_offset_y),
    ]

    prev_interp = bpy.context.preferences.edit.keyframe_new_interpolation_type
    bpy.context.preferences.edit.keyframe_new_interpolation_type = 'BEZIER'
    try:
        transform = strip.transform
        for frame, ox, oy in keyframe_points:
            transform.offset_x = ox
            transform.offset_y = oy
            # NOTE: keyframe_insert must be called on the sub-struct that
            # actually owns the property (transform), not on the strip
            # with a dotted "transform.offset_x" path — Blender 5.x
            # rejects that.
            transform.keyframe_insert(data_path="offset_x", frame=frame)
            transform.keyframe_insert(data_path="offset_y", frame=frame)
    finally:
        bpy.context.preferences.edit.keyframe_new_interpolation_type = prev_interp


# ---------------------------------------------------------------------------
# BUILD THE VSE SEQUENCE
# ---------------------------------------------------------------------------
def main():
    for path in (LEFT_VIDEO_PATH, RIGHT_VIDEO_PATH):
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"Video file not found: {path}\n"
                f"Update LEFT_VIDEO_PATH / RIGHT_VIDEO_PATH at the top of this script."
            )

    scene = bpy.context.scene
    scene.render.resolution_x = TOTAL_WIDTH
    scene.render.resolution_y = HEIGHT
    scene.render.resolution_percentage = 100
    scene.render.fps = FPS

    if scene.sequence_editor is None:
        scene.sequence_editor_create()
    seq_editor = scene.sequence_editor

    # Default interpolation for newly inserted keyframes (used as-is for
    # the black-cover fades; animate_reposition() temporarily switches
    # this to BEZIER around its own inserts, then restores it).
    bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'

    seq = seq_editor.strips if hasattr(seq_editor, "strips") else seq_editor.sequences

    for strip in list(seq):
        seq.remove(strip)

    left_offset_x = -(TOTAL_WIDTH / 2) + (LEFT_WIDTH / 2)   # -656
    right_offset_x = (TOTAL_WIDTH / 2) - (RIGHT_WIDTH / 2)  # +304

    # ---- Left video (channel 1) ----
    left_strip = seq.new_movie(
        name="LeftVideo", filepath=LEFT_VIDEO_PATH, channel=1, frame_start=1
    )
    elem = left_strip.elements[0]
    apply_cover_fit(left_strip, LEFT_WIDTH, HEIGHT, elem.orig_width, elem.orig_height)
    left_strip.transform.offset_x = left_offset_x
    left_strip.transform.offset_y = 0

    # ---- Right video (channel 2) ----
    right_strip = seq.new_movie(
        name="RightVideo", filepath=RIGHT_VIDEO_PATH, channel=2, frame_start=1
    )
    elem = right_strip.elements[0]
    apply_cover_fit(right_strip, RIGHT_WIDTH, HEIGHT, elem.orig_width, elem.orig_height)
    right_strip.transform.offset_x = right_offset_x
    right_strip.transform.offset_y = 0

    # ---- Black cover strips (channels 3+, one per switch-off window) ----
    next_channel = 3
    fade_frames = round(FADE_SECONDS * FPS)
    black_strips = []

    tmp_dir = os.path.join(os.path.dirname(OUTPUT_PATH), "_black_cover_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    for start_seconds, end_seconds in SWITCH_OFF_RANGES.get("left", []):
        start_frame = seconds_to_frame(start_seconds, FPS)
        end_frame = seconds_to_frame(end_seconds, FPS)
        black_strips.append(add_black_cover(
            seq, f"LeftBlack_{start_frame}_{end_frame}", next_channel,
            start_frame, end_frame, LEFT_WIDTH, left_offset_x, fade_frames, tmp_dir,
        ))
        next_channel += 1

    for start_seconds, end_seconds in SWITCH_OFF_RANGES.get("right", []):
        start_frame = seconds_to_frame(start_seconds, FPS)
        end_frame = seconds_to_frame(end_seconds, FPS)
        black_strips.append(add_black_cover(
            seq, f"RightBlack_{start_frame}_{end_frame}", next_channel,
            start_frame, end_frame, RIGHT_WIDTH, right_offset_x, fade_frames, tmp_dir,
        ))
        next_channel += 1

    # ---- Reposition ("travel") animations — independent feature ----
    reposition_fade_frames = round(REPOSITION_FADE_SECONDS * FPS)

    for start_seconds, end_seconds, target_x, target_y in REPOSITION_RANGES.get("left", []):
        start_frame = seconds_to_frame(start_seconds, FPS)
        end_frame = seconds_to_frame(end_seconds, FPS)
        animate_reposition(
            scene, left_strip, left_offset_x, 0, target_x, target_y,
            start_frame, end_frame, reposition_fade_frames,
        )

    for start_seconds, end_seconds, target_x, target_y in REPOSITION_RANGES.get("right", []):
        start_frame = seconds_to_frame(start_seconds, FPS)
        end_frame = seconds_to_frame(end_seconds, FPS)
        animate_reposition(
            scene, right_strip, right_offset_x, 0, target_x, target_y,
            start_frame, end_frame, reposition_fade_frames,
        )

    # ---- Timeline length: match the longer of the two clips ----
    total_frames = max(left_strip.frame_final_duration, right_strip.frame_final_duration)
    scene.frame_start = 1
    scene.frame_end = total_frames

    # ---- Output settings (MP4 via FFMPEG) ----
    scene.render.filepath = OUTPUT_PATH
    scene.render.image_settings.media_type = 'VIDEO'
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'
    scene.render.ffmpeg.constant_rate_factor = 'HIGH'

    print(f"Left  video: {LEFT_VIDEO_PATH}")
    print(f"  black-out windows (seconds): {SWITCH_OFF_RANGES.get('left', [])}")
    print(f"  reposition windows (seconds, target xy): {REPOSITION_RANGES.get('left', [])}")
    print(f"Right video: {RIGHT_VIDEO_PATH}")
    print(f"  black-out windows (seconds): {SWITCH_OFF_RANGES.get('right', [])}")
    print(f"  reposition windows (seconds, target xy): {REPOSITION_RANGES.get('right', [])}")
    print(f"Timeline: frame 1 to {total_frames} @ {FPS}fps")
    print(f"Output will be written to: {OUTPUT_PATH}")

    return scene, black_strips


scene, black_strips = main()

# ---------------------------------------------------------------------------
# Render immediately (fully headless):
#   blender --background --python combine_split_screen_with_switches_and_shift.py
# ---------------------------------------------------------------------------
bpy.ops.render.render(animation=True)
print(f"Render complete. Video saved to: {OUTPUT_PATH}")
