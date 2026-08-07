"""
Headless Blender — Side-by-Side Video Combiner WITH Manual On/Off Switching
=============================================================================

Same layout as combine_split_screen.py (left 608x1080 / right 1312x1080 ->
1920x1080), but you can now specify time windows where either side goes
BLACK while the other side keeps playing normally. No repositioning —
the blacked-out panel just shows black in the exact same spot.

HOW TO SET SWITCH-OFF WINDOWS
------------------------------
Edit the SWITCH_OFF_RANGES dict below. Each entry is a list of
(start_seconds, end_seconds) tuples (inclusive) during which that side
goes black. Times are in SECONDS on the final combined video's timeline
(0.0 = very first frame). They're converted to frames internally using FPS.

Example:
    SWITCH_OFF_RANGES = {
        "left":  [(1.5, 3.0), (10.0, 11.5)],   # left goes black twice
        "right": [(5.0, 7.5)],                 # right goes black once
    }
Leave a list empty ([]) if that side should never go black.

RUN (fully headless, no window):
    blender --background --python combine_split_screen_with_switches.py
"""

import bpy
import os

# ---------------------------------------------------------------------------
# CONFIG — edit paths and switch-off windows here
# ---------------------------------------------------------------------------
LEFT_VIDEO_PATH = r"C:\Users\saket\Documents\Manim\teaser2.mp4"
RIGHT_VIDEO_PATH = r"C:\Users\saket\Documents\Manim\media\videos\cubes_collide_and_multiply\1080p30\CubesCollideAndMultiply.mp4"

LEFT_WIDTH = 608
RIGHT_WIDTH = 1312
HEIGHT = 1080
TOTAL_WIDTH = LEFT_WIDTH + RIGHT_WIDTH  # 1920

FPS = 30

# How long the fade-to-black / fade-back-to-video transition takes, in
# seconds, at the start and end of each switch-off window.
FADE_SECONDS = 0.4

# ---- EDIT THIS: (start_seconds, end_seconds) inclusive, per side ----
SWITCH_OFF_RANGES = {
    "left": [
        (3, 6),   # left panel goes black from 1.5s to 3.0s
    ],
    "right": [
        (7.0, 9.0),   # right panel goes black from 5.0s to 7.0s
    ],
}

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "final_split_screen_with_switches.mp4"
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


def add_black_cover(seq, name, channel, start_frame, end_frame, target_width, offset_x, fade_frames):
    """Add a solid black strip exactly covering one panel, for frames
    [start_frame, end_frame] inclusive, fading in/out at its edges instead
    of switching instantly."""
    black = seq.new_effect(
        name=name, type='COLOR', channel=channel,
        frame_start=start_frame, length=(end_frame - start_frame + 1),
    )
    black.color = (0.0, 0.0, 0.0)

    # Color strips are generated at full scene resolution (1920x1080), so
    # scale/position them the same way we do for video strips to exactly
    # cover just this one panel.
    apply_cover_fit(black, target_width, HEIGHT, TOTAL_WIDTH, HEIGHT)
    black.transform.offset_x = offset_x
    black.transform.offset_y = 0

    # ---- Fade in at the start, fade out at the end (crossfade to/from
    # the video playing underneath) ----
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

    # Linear keyframes for the fade animation, set via preferences rather
    # than looping through Action.fcurves (Blender 5.x changed that API).
    bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'

    # Blender 5.x renamed "Sequence" -> "Strip"; support both collection names.
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
    # placed above BOTH video channels so they fully occlude whichever
    # side they're covering, regardless of that side's channel number.
    next_channel = 3
    fade_frames = round(FADE_SECONDS * FPS)

    for start_seconds, end_seconds in SWITCH_OFF_RANGES.get("left", []):
        start_frame = seconds_to_frame(start_seconds, FPS)
        end_frame = seconds_to_frame(end_seconds, FPS)
        add_black_cover(
            seq, f"LeftBlack_{start_frame}_{end_frame}", next_channel,
            start_frame, end_frame, LEFT_WIDTH, left_offset_x, fade_frames,
        )
        next_channel += 1

    for start_seconds, end_seconds in SWITCH_OFF_RANGES.get("right", []):
        start_frame = seconds_to_frame(start_seconds, FPS)
        end_frame = seconds_to_frame(end_seconds, FPS)
        add_black_cover(
            seq, f"RightBlack_{start_frame}_{end_frame}", next_channel,
            start_frame, end_frame, RIGHT_WIDTH, right_offset_x, fade_frames,
        )
        next_channel += 1

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
    print(f"Right video: {RIGHT_VIDEO_PATH}")
    print(f"  black-out windows (seconds): {SWITCH_OFF_RANGES.get('right', [])}")
    print(f"Timeline: frame 1 to {total_frames} @ {FPS}fps")
    print(f"Output will be written to: {OUTPUT_PATH}")


main()

# ---------------------------------------------------------------------------
# Render immediately (fully headless):
#   blender --background --python combine_split_screen_with_switches.py
# ---------------------------------------------------------------------------
bpy.ops.render.render(animation=True)
print(f"Render complete. Video saved to: {OUTPUT_PATH}")
