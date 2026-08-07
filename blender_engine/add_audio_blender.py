import bpy
import os

# ============================================================
# CONFIG
# ============================================================

VIDEO_PATH = r"C:\Users\saket\Documents\Manim\zoom_test_output_multiple_coordinate.mp4"

OUTPUT_PATH = r"C:\Users\saket\Documents\Manim\zoom_test_output_multiple_coordinate_withaudio.mp4"

# Keep the video's original audio?
KEEP_VIDEO_AUDIO = False

FPS = 30

# ============================================================
# AUDIO TRACKS
#
# Format:
# (filepath, start_time_seconds, volume)
#
# You can add as many tracks as you want.
#
# Example:
#
# AUDIO_TRACKS = [
#     (r"C:\Audio\music.mp3",      0.0, 0.25),
#     (r"C:\Audio\voice.wav",      5.5, 1.00),
#     (r"C:\Audio\effect.wav",    18.2, 0.80),
# ]
#
# If you only want ONE audio:
#
# AUDIO_TRACKS = [
#     (r"C:\Audio\music.mp3", 0.0, 0.40),
# ]
#
# ============================================================

AUDIO_TRACKS = [

    (
        r"C:\Users\saket\Documents\Manim\Quiz_audio.mpeg",
        4.0,
        1.0,
    ),


]

# ============================================================
# HELPERS
# ============================================================

def seconds_to_frame(seconds):
    return round(seconds * FPS) + 1


# ============================================================
# SCENE
# ============================================================

scene = bpy.context.scene

if scene.sequence_editor is None:
    scene.sequence_editor_create()

seq_editor = scene.sequence_editor
seq = seq_editor.strips if hasattr(seq_editor, "strips") else seq_editor.sequences

# Remove existing strips
for strip in list(seq):
    seq.remove(strip)

# ============================================================
# VIDEO
# ============================================================

if not os.path.isfile(VIDEO_PATH):
    raise FileNotFoundError(VIDEO_PATH)

video = seq.new_movie(
    name="Video",
    filepath=VIDEO_PATH,
    channel=1,
    frame_start=1,
)

# ============================================================
# ORIGINAL VIDEO AUDIO
# ============================================================

if KEEP_VIDEO_AUDIO:

    seq.new_sound(
        name="Original Audio",
        filepath=VIDEO_PATH,
        channel=2,
        frame_start=1,
    )

# ============================================================
# RENDER SETTINGS
# ============================================================

scene.render.resolution_x = video.elements[0].orig_width
scene.render.resolution_y = video.elements[0].orig_height
scene.render.resolution_percentage = 100
scene.render.fps = FPS

scene.frame_start = 1
scene.frame_end = int(video.frame_final_end)

video_duration_seconds = scene.frame_end / FPS

# ============================================================
# ADD AUDIO TRACKS
# ============================================================

audio_channel = 3

for filepath, start_time, volume in AUDIO_TRACKS:

    if not os.path.isfile(filepath):
        raise FileNotFoundError(filepath)

    if start_time >= video_duration_seconds:

        print(
            f"Skipping {os.path.basename(filepath)} "
            f"(starts at {start_time}s, video is only "
            f"{video_duration_seconds:.2f}s)"
        )

        continue

    trim_frames = int(start_time * FPS)

    sound = seq.new_sound(
        name=os.path.basename(filepath),
        filepath=filepath,
        channel=audio_channel,
        frame_start=1,
    )

    # Trim the beginning of the media
    sound.content_trim_start = trim_frames

    # Move the strip back to frame 1
    sound.frame_start = 1

    sound.volume = volume

    print("Trim:", sound.content_trim_start)

    audio_channel += 1

# ============================================================
# OUTPUT SETTINGS
# ============================================================

scene.render.filepath = OUTPUT_PATH

img = scene.render.image_settings

# IMPORTANT: set media type BEFORE file format
img.media_type = 'VIDEO'
img.file_format = 'FFMPEG'

scene.render.ffmpeg.format = 'MPEG4'
scene.render.ffmpeg.codec = 'H264'

scene.render.ffmpeg.audio_codec = 'AAC'
scene.render.ffmpeg.audio_bitrate = 192

# ============================================================
# INFO
# ============================================================

print()
print("=" * 60)
print("Video :", VIDEO_PATH)
print("Output:", OUTPUT_PATH)
print(f"Duration: {video_duration_seconds:.2f} seconds")
print()

print("Audio Tracks:")

if not AUDIO_TRACKS:
    print("  None")

for filepath, start_time, volume in AUDIO_TRACKS:

    print(
        f"  {os.path.basename(filepath)}"
        f" | start={start_time}s"
        f" | volume={volume}"
    )

print("=" * 60)
print()

# ============================================================
# RENDER
# ============================================================

print("Rendering...")

bpy.ops.render.render(animation=True)

print("Done.")
print("Saved to:", OUTPUT_PATH)