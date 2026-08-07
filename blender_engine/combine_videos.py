import bpy
import os

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

VIDEO_PATHS = [
    r"C:\Users\saket\Documents\Manim\zoom_test_output1.mp4",
    r"C:\Users\saket\Documents\Manim\zoom_test_output2.mp4",
    r"C:\Users\saket\Documents\Manim\zoom_test_output3.mp4",
]

OUTPUT_PATH = r"C:\Videos\combined_output.mp4"

# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

scene = bpy.context.scene

if scene.sequence_editor is None:
    scene.sequence_editor_create()

seq_editor = scene.sequence_editor
seq = seq_editor.strips if hasattr(seq_editor, "strips") else seq_editor.sequences

# Remove existing strips
for strip in list(seq):
    seq.remove(strip)

current_frame = 1
first = True

for video in VIDEO_PATHS:

    if not os.path.isfile(video):
        raise FileNotFoundError(video)

    strip = seq.new_movie(
        name=os.path.basename(video),
        filepath=video,
        channel=1,
        frame_start=current_frame,
    )

    if first:
        elem = strip.elements[0]

        scene.render.resolution_x = elem.orig_width
        scene.render.resolution_y = elem.orig_height
        scene.render.resolution_percentage = 100
        scene.render.fps = scene.render.fps

        first = False

    current_frame += strip.frame_final_duration

scene.frame_start = 1
scene.frame_end = current_frame - 1

scene.render.filepath = OUTPUT_PATH
scene.render.image_settings.media_type = 'VIDEO'
scene.render.image_settings.file_format = 'FFMPEG'
scene.render.ffmpeg.format = 'MPEG4'
scene.render.ffmpeg.codec = 'H264'
scene.render.ffmpeg.constant_rate_factor = 'HIGH'

print("Rendering...")
bpy.ops.render.render(animation=True)
print("Done.")