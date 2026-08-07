#This combines two videos in Blender, width and hieght can be changed according to the attached video's and desired combined output video's aspect ratio

"""
Headless Blender — Side-by-Side Video Combiner (VSE)
=======================================================

Combines two ALREADY-RENDERED video files into one 1920x1080 video:

    LEFT_VIDEO_PATH  : 608  x 1080  -> placed on the left
    RIGHT_VIDEO_PATH : 1312 x 1080  -> placed on the right (e.g. your Manim render)

Uses Blender's Video Sequence Editor (VSE) rather than the 3D compositor,
since we're combining two finished video files, not live 3D scenes.

BEFORE RUNNING
--------------
1. Render your Manim animation first, e.g.:
     manim -pql cubes_collide_and_multiply.py CubesCollideAndMultiply
   Find the output .mp4 under: media/videos/<script_name>/<quality>/<SceneName>.mp4

2. Edit the two path variables below (LEFT_VIDEO_PATH, RIGHT_VIDEO_PATH)
   to point at your actual files.

3. Make sure both source videos share the same frame rate (this script
   assumes 30 fps — change FPS below if yours differ). If left/right clips
   have different native fps, Blender will still play every frame but at
   the PROJECT fps, so a mismatch will make one clip look sped up/slowed
   down relative to the other.

RUN (fully headless, no window):
    blender --background --python combine_split_screen.py
"""

import bpy
import os

# ---------------------------------------------------------------------------
# CONFIG — edit these two paths for your actual files
# ---------------------------------------------------------------------------
LEFT_VIDEO_PATH = r"C:\Users\saket\Documents\Manim\Entropy_teaser_video.mp4"
RIGHT_VIDEO_PATH = r"C:\Users\saket\Documents\Manim\media\videos\cubes_collide_and_multiply\1080p30\CubesCollideAndMultiply.mp4"

LEFT_WIDTH = 608
RIGHT_WIDTH = 1312
HEIGHT = 1080
TOTAL_WIDTH = LEFT_WIDTH + RIGHT_WIDTH  # 1920

FPS = 30

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "final_split_screen_output.mp4"
)


def apply_cover_fit(strip, target_width, target_height):
    """Uniformly scale a strip so it fully fills a target_width x target_height
    box (cropping any overflow) instead of leaving letterbox gaps when the
    source video's native resolution doesn't match the panel exactly."""
    elem = strip.elements[0]
    orig_w, orig_h = elem.orig_width, elem.orig_height
    scale = max(target_width / orig_w, target_height / orig_h)
    strip.transform.scale_x = scale
    strip.transform.scale_y = scale


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

    # Blender 5.x renamed the VSE's "Sequence" type to "Strip", and the
    # collection property on SequenceEditor appears to have moved from
    # `.sequences` to `.strips` accordingly. Support both so this script
    # keeps working across versions.
    if hasattr(seq_editor, "strips"):
        seq = seq_editor.strips
    else:
        seq = seq_editor.sequences

    # clear any pre-existing strips (safe to re-run this script)
    for strip in list(seq):
        seq.remove(strip)

    # ---- Left strip ----
    left_strip = seq.new_movie(
        name="LeftVideo", filepath=LEFT_VIDEO_PATH, channel=1, frame_start=1
    )
    apply_cover_fit(left_strip, LEFT_WIDTH, HEIGHT)
    # canvas center = (0,0); offset so this strip's own center lands on the
    # left panel's center within the 1920-wide frame
    left_strip.transform.offset_x = -(TOTAL_WIDTH / 2) + (LEFT_WIDTH / 2)  # -656
    left_strip.transform.offset_y = 0

    # ---- Right strip (e.g. the Manim render) ----
    right_strip = seq.new_movie(
        name="RightVideo", filepath=RIGHT_VIDEO_PATH, channel=2, frame_start=1
    )
    apply_cover_fit(right_strip, RIGHT_WIDTH, HEIGHT)
    right_strip.transform.offset_x = (TOTAL_WIDTH / 2) - (RIGHT_WIDTH / 2)  # +304
    right_strip.transform.offset_y = 0

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

    print(f"Left  strip: {LEFT_VIDEO_PATH}  ({LEFT_WIDTH}x{HEIGHT}, offset_x={left_strip.transform.offset_x})")
    print(f"Right strip: {RIGHT_VIDEO_PATH} ({RIGHT_WIDTH}x{HEIGHT}, offset_x={right_strip.transform.offset_x})")
    print(f"Timeline: frame 1 to {total_frames} @ {FPS}fps")
    print(f"Output will be written to: {OUTPUT_PATH}")


main()

# ---------------------------------------------------------------------------
# Render immediately (fully headless):
#   blender --background --python combine_split_screen.py
# ---------------------------------------------------------------------------
bpy.ops.render.render(animation=True)
print(f"Render complete. Video saved to: {OUTPUT_PATH}")
