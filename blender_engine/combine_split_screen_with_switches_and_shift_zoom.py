"""
Headless Blender — Side-by-Side Video Combiner
WITH Manual On/Off Switching AND Position-Shift ("Travel") Animation
=============================================================================

Same layout as before (left 608x1080 / right 1312x1080 -> 1920x1080).

TWO INDEPENDENT FEATURES — use either, or both together:

1) SWITCH_OFF_RANGES
   A side fades to fully transparent for a time window, revealing a
   full-canvas black background layer underneath. Fades over
   FADE_SECONDS. IMPORTANT CHANGE from the previous version: this is now
   done by animating that side's OWN strip opacity (blend_alpha), NOT by
   placing a black rectangle on top of it at a fixed screen position.
   That's what let a repositioned strip get "eaten" by a switch-off
   rectangle sized for the untouched panel — see REPOSITION_RANGES notes
   below.

2) REPOSITION_RANGES
   A side's video SLIDES (travels) from its normal split-screen position
   to a target offset, holds there, then slides back. Size (scale) is
   NOT changed — this is a pure position move, same panel size. It eases
   in/out (smooth acceleration/deceleration) instead of moving at
   constant speed, so it reads as a "travel" rather than a snap.

   This is completely independent of SWITCH_OFF_RANGES: it always
   animates a side's OWN strip. If you want "left slides to center while
   right is off", just set matching/overlapping time windows in both
   dicts — SWITCH_OFF_RANGES["right"] and REPOSITION_RANGES["left"].

WHY THE LAYERING CHANGED
-------------------------
Old approach: "off" was a black PNG rectangle placed on a HIGHER channel,
sized and positioned to exactly cover one panel. That works fine as long
as nothing else moves. But once the other side's video is repositioned
(e.g. slides toward center), it can slide UNDER that rectangle's fixed
screen position and get visually clipped/covered — which is exactly the
bug you saw (left video sliding right disappeared partway, because the
right side's black cover rectangle was still sitting over that same
screen region on a higher channel).

New approach:
  Channel 1: one full-canvas (1920x1080) black image, always present,
             for the entire timeline. This is the "nothing here" layer.
  Channel 2: left video
  Channel 3: right video
"Switching off" a side now means animating THAT STRIP'S OWN blend_alpha
from 1 -> 0 -> 0 -> 1 (instead of covering it with something else). At
alpha 0 the strip is fully transparent, so whatever is on the channels
below shows through — the black base layer if nothing else is there, or
another video strip if one has been repositioned into that space. This
means repositioning and switching-off can never fight over screen
position again, because "off" no longer has a screen position at all.

HOW TO SET SWITCH-OFF WINDOWS
------------------------------
Edit SWITCH_OFF_RANGES. Each entry is (start_seconds, end_seconds),
inclusive, during which that side fades out (to transparent/black).

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

HOW TO SET ZOOM-IN (FIT-TO-CANVAS) WINDOWS
--------------------------------------------
Edit ZOOM_RANGES. Each entry is (start_seconds, end_seconds) during which
that side's video scales UP from its normal small panel size to fully
fill the entire 1920x1080 canvas (re-centered at 0,0 while it does),
holds there, then scales back down to its normal panel size/position.

This is for a video whose panel is much smaller than the canvas (e.g.
the 608px-wide left panel) and you want it to briefly take over the
whole frame instead of just sliding around within its own size — think
"punch in to fullscreen" rather than "slide to a new spot".

    ZOOM_RANGES = {
        "left": [
            (10.0, 13.0),   # left video zooms to fill the whole canvas
        ],
        "right": [],
    }

Leave a list empty ([]) if that side should never zoom.

NOTE: zoom and reposition both animate offset_x/offset_y on the same
strip. Don't schedule ZOOM_RANGES and REPOSITION_RANGES on the SAME side
with OVERLAPPING time windows — they'll fight over the same keyframes.
Combining zoom on one side with switch-off on the other side is fine
(that's the common case: one side fills the screen while the other is
off).

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

# Fade-out / fade-back-in duration for switch-off windows.
FADE_SECONDS = 0.4

# Ease-in / ease-out duration for reposition (travel) windows. Kept
# separate from FADE_SECONDS since they're independent features and you
# may want the slide to happen faster/slower than the opacity fade.
REPOSITION_FADE_SECONDS = 0.5

# ---- EDIT THIS: switch-off (fade-to-transparent) windows, per side ----
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

# Ease-in / ease-out duration for zoom-to-fullscreen windows.
ZOOM_FADE_SECONDS = 0.5

# ---- EDIT THIS: zoom-to-fullscreen windows, per side ----
# (start_seconds, end_seconds) — target is always "fill the whole canvas"
##Code snippet
##ZOOM_RANGES = {
  ##  "left": [],
    ##"right": [],
##}

ZOOM_RANGES = {
    "left": [
        (10.0, 13.0),   # left video zooms to fill the whole canvas
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
    img = bpy.data.images.new("TempBlackBase", width=width, height=height, alpha=False)
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)


def add_black_base(seq, channel, start_frame, duration_frames, tmp_dir):
    """Add ONE full-canvas black image strip on the lowest channel, present
    for the whole timeline. This is what shows through when a video strip's
    opacity is faded down for a switch-off window. Using a real image (not
    a generator 'COLOR' effect strip) sidesteps a Blender 5.2 VSE bug where
    full-canvas generator strips can silently fail to composite."""
    png_path = os.path.join(tmp_dir, "black_base.png")
    create_black_png(TOTAL_WIDTH, HEIGHT, png_path)

    black = seq.new_image(
        name="BlackBase", filepath=png_path, channel=channel, frame_start=start_frame,
    )
    black.frame_final_duration = duration_frames
    black.transform.offset_x = 0
    black.transform.offset_y = 0
    black.blend_alpha = 1.0
    return black


def animate_switch_off(strip, start_frame, end_frame, fade_frames):
    """Fade `strip`'s OWN opacity down to fully transparent and back, instead
    of covering it with a black rectangle. This is what lets another strip
    (e.g. a repositioned one) show through underneath during the "off"
    window, and — just as importantly — means this strip's "off" state has
    no fixed screen position, so it can never clip a strip that has been
    moved elsewhere on the canvas.
    """
    duration = end_frame - start_frame
    fade = min(fade_frames, duration // 2) if duration > 0 else 0

    strip.blend_alpha = 1.0
    strip.keyframe_insert(data_path="blend_alpha", frame=start_frame)
    strip.blend_alpha = 0.0
    strip.keyframe_insert(data_path="blend_alpha", frame=start_frame + fade)
    strip.blend_alpha = 0.0
    strip.keyframe_insert(data_path="blend_alpha", frame=end_frame - fade)
    strip.blend_alpha = 1.0
    strip.keyframe_insert(data_path="blend_alpha", frame=end_frame)


def animate_reposition(strip, original_offset_x, original_offset_y,
                        target_offset_x, target_offset_y,
                        start_frame, end_frame, fade_frames):
    """Make `strip` travel from its normal position to
    (target_offset_x, target_offset_y), hold, then travel back — timed
    independently of any switch-off/opacity animation. Size/scale is left
    untouched (position-only move).

    Uses Bezier keyframes (auto handles) for this strip's move, which
    naturally eases in/out — smooth accelerate-then-decelerate — instead
    of the constant-speed Linear interpolation used for the opacity fades.
    We flip the global "new keyframe" interpolation setting around just
    this insertion instead of reaching into Action/F-Curve internals
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


def compute_fullscreen_scale(source_width, source_height):
    """Same 'cover' logic as apply_cover_fit, but against the FULL canvas
    instead of a panel — the scale factor needed so the source fully fills
    1920x1080 (cropping any overflow) with no letterboxing."""
    return max(TOTAL_WIDTH / source_width, HEIGHT / source_height)


def animate_zoom_fullscreen(strip, orig_scale_x, orig_scale_y, orig_offset_x, orig_offset_y,
                             source_width, source_height,
                             start_frame, end_frame, fade_frames):
    """Make `strip` scale up from its normal panel size/position to fully
    fill the 1920x1080 canvas (re-centered at offset 0,0), hold, then scale
    back down to its original panel size/position. New, independent
    feature — does not touch anything the switch-off or reposition
    features do, and doesn't require editing them.

    Animates scale_x/scale_y AND offset_x/offset_y together (the same
    transform sub-struct reposition uses) with eased Bezier keyframes, for
    the same "smooth travel" feel as animate_reposition.
    """
    target_scale = compute_fullscreen_scale(source_width, source_height)
    target_offset_x = 0
    target_offset_y = 0

    duration = end_frame - start_frame
    fade = min(fade_frames, duration // 2) if duration > 0 else 0

    keyframe_points = [
        (start_frame, orig_scale_x, orig_scale_y, orig_offset_x, orig_offset_y),
        (start_frame + fade, target_scale, target_scale, target_offset_x, target_offset_y),
        (end_frame - fade, target_scale, target_scale, target_offset_x, target_offset_y),
        (end_frame, orig_scale_x, orig_scale_y, orig_offset_x, orig_offset_y),
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
    # the switch-off opacity fades; animate_reposition() temporarily
    # switches this to BEZIER around its own inserts, then restores it).
    bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'

    seq = seq_editor.strips if hasattr(seq_editor, "strips") else seq_editor.sequences

    for strip in list(seq):
        seq.remove(strip)

    left_offset_x = -(TOTAL_WIDTH / 2) + (LEFT_WIDTH / 2)   # -656
    right_offset_x = (TOTAL_WIDTH / 2) - (RIGHT_WIDTH / 2)  # +304

    # ---- Left video (channel 2) ----
    left_strip = seq.new_movie(
        name="LeftVideo", filepath=LEFT_VIDEO_PATH, channel=2, frame_start=1
    )
    elem = left_strip.elements[0]
    left_src_w, left_src_h = elem.orig_width, elem.orig_height
    apply_cover_fit(left_strip, LEFT_WIDTH, HEIGHT, left_src_w, left_src_h)
    left_scale = left_strip.transform.scale_x  # captured for the zoom feature's "return to normal" target
    left_strip.transform.offset_x = left_offset_x
    left_strip.transform.offset_y = 0
    left_strip.blend_type = 'ALPHA_OVER'
    left_strip.blend_alpha = 1.0

    # ---- Right video (channel 3) ----
    right_strip = seq.new_movie(
        name="RightVideo", filepath=RIGHT_VIDEO_PATH, channel=3, frame_start=1
    )
    elem = right_strip.elements[0]
    right_src_w, right_src_h = elem.orig_width, elem.orig_height
    apply_cover_fit(right_strip, RIGHT_WIDTH, HEIGHT, right_src_w, right_src_h)
    right_scale = right_strip.transform.scale_x  # captured for the zoom feature's "return to normal" target
    right_strip.transform.offset_x = right_offset_x
    right_strip.transform.offset_y = 0
    right_strip.blend_type = 'ALPHA_OVER'
    right_strip.blend_alpha = 1.0

    # ---- Timeline length: match the longer of the two clips ----
    total_frames = max(left_strip.frame_final_duration, right_strip.frame_final_duration)
    scene.frame_start = 1
    scene.frame_end = total_frames

    # ---- Full-canvas black base layer (channel 1, bottom, whole timeline) ----
    tmp_dir = os.path.join(os.path.dirname(OUTPUT_PATH), "_black_base_tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    black_base = add_black_base(seq, channel=1, start_frame=1, duration_frames=total_frames, tmp_dir=tmp_dir)

    # ---- Switch-off (opacity fade) — animates each video's OWN strip ----
    fade_frames = round(FADE_SECONDS * FPS)

    for start_seconds, end_seconds in SWITCH_OFF_RANGES.get("left", []):
        start_frame = seconds_to_frame(start_seconds, FPS)
        end_frame = seconds_to_frame(end_seconds, FPS)
        animate_switch_off(left_strip, start_frame, end_frame, fade_frames)

    for start_seconds, end_seconds in SWITCH_OFF_RANGES.get("right", []):
        start_frame = seconds_to_frame(start_seconds, FPS)
        end_frame = seconds_to_frame(end_seconds, FPS)
        animate_switch_off(right_strip, start_frame, end_frame, fade_frames)

    # ---- Reposition ("travel") animations — independent feature ----
    reposition_fade_frames = round(REPOSITION_FADE_SECONDS * FPS)

    for start_seconds, end_seconds, target_x, target_y in REPOSITION_RANGES.get("left", []):
        start_frame = seconds_to_frame(start_seconds, FPS)
        end_frame = seconds_to_frame(end_seconds, FPS)
        animate_reposition(
            left_strip, left_offset_x, 0, target_x, target_y,
            start_frame, end_frame, reposition_fade_frames,
        )

    for start_seconds, end_seconds, target_x, target_y in REPOSITION_RANGES.get("right", []):
        start_frame = seconds_to_frame(start_seconds, FPS)
        end_frame = seconds_to_frame(end_seconds, FPS)
        animate_reposition(
            right_strip, right_offset_x, 0, target_x, target_y,
            start_frame, end_frame, reposition_fade_frames,
        )

    # ---- Zoom-to-fullscreen animations — independent feature, new ----
    zoom_fade_frames = round(ZOOM_FADE_SECONDS * FPS)

    for start_seconds, end_seconds in ZOOM_RANGES.get("left", []):
        start_frame = seconds_to_frame(start_seconds, FPS)
        end_frame = seconds_to_frame(end_seconds, FPS)
        animate_zoom_fullscreen(
            left_strip, left_scale, left_scale, left_offset_x, 0,
            left_src_w, left_src_h, start_frame, end_frame, zoom_fade_frames,
        )

    for start_seconds, end_seconds in ZOOM_RANGES.get("right", []):
        start_frame = seconds_to_frame(start_seconds, FPS)
        end_frame = seconds_to_frame(end_seconds, FPS)
        animate_zoom_fullscreen(
            right_strip, right_scale, right_scale, right_offset_x, 0,
            right_src_w, right_src_h, start_frame, end_frame, zoom_fade_frames,
        )

    # ---- Output settings (MP4 via FFMPEG) ----
    scene.render.filepath = OUTPUT_PATH
    scene.render.image_settings.media_type = 'VIDEO'
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'
    scene.render.ffmpeg.constant_rate_factor = 'HIGH'

    print(f"Left  video: {LEFT_VIDEO_PATH}")
    print(f"  switch-off windows (seconds): {SWITCH_OFF_RANGES.get('left', [])}")
    print(f"  reposition windows (seconds, target xy): {REPOSITION_RANGES.get('left', [])}")
    print(f"  zoom-to-fullscreen windows (seconds): {ZOOM_RANGES.get('left', [])}")
    print(f"Right video: {RIGHT_VIDEO_PATH}")
    print(f"  switch-off windows (seconds): {SWITCH_OFF_RANGES.get('right', [])}")
    print(f"  reposition windows (seconds, target xy): {REPOSITION_RANGES.get('right', [])}")
    print(f"  zoom-to-fullscreen windows (seconds): {ZOOM_RANGES.get('right', [])}")
    print(f"Timeline: frame 1 to {total_frames} @ {FPS}fps")
    print(f"Output will be written to: {OUTPUT_PATH}")

    return scene, black_base


scene, black_base = main()

# ---------------------------------------------------------------------------
# Render immediately (fully headless):
#   blender --background --python combine_split_screen_with_switches_and_shift.py
# ---------------------------------------------------------------------------
bpy.ops.render.render(animation=True)
print(f"Render complete. Video saved to: {OUTPUT_PATH}")
