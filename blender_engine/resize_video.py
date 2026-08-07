import cv2
import numpy as np
from ultralytics import YOLO
import subprocess
import os

# =====================================================
# CONFIG
# =====================================================

INPUT_VIDEO = "arena1.mp4"
TEMP_VIDEO = "arenatemp.mp4"
OUTPUT_VIDEO = "arena2.mp4"

OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920

TARGET_RATIO = OUTPUT_WIDTH / OUTPUT_HEIGHT   # 9:16 = 0.5625

SMOOTHING = 0.90

# =====================================================
# LOAD MODEL
# =====================================================

model = YOLO("yolo11n.pt")

# =====================================================
# OPEN VIDEO
# =====================================================

cap = cv2.VideoCapture(INPUT_VIDEO)

fps = cap.get(cv2.CAP_PROP_FPS)

frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

print("Input:", frame_width, "x", frame_height)

# =====================================================
# DETERMINE CROP SIZE
# =====================================================

current_ratio = frame_width / frame_height

if current_ratio > TARGET_RATIO:
    # Video is wider than 9:16
    crop_height = frame_height
    crop_width = int(frame_height * TARGET_RATIO)
else:
    # Video is taller/narrower than 9:16
    crop_width = frame_width
    crop_height = int(frame_width / TARGET_RATIO)

print("Crop:", crop_width, "x", crop_height)

# =====================================================
# OUTPUT WRITER
# =====================================================

writer = cv2.VideoWriter(
    TEMP_VIDEO,
    cv2.VideoWriter_fourcc(*'mp4v'),
    fps,
    (OUTPUT_WIDTH, OUTPUT_HEIGHT)
)

# =====================================================
# INITIAL CAMERA POSITION
# =====================================================

camera_x = frame_width // 2
camera_y = frame_height // 2

# =====================================================
# PROCESS VIDEO
# =====================================================

frame_count = 0

while True:

    ret, frame = cap.read()

    if not ret:
        break

    frame_count += 1

    # ----------------------------------------
    # Detect objects
    # ----------------------------------------

    results = model(frame, verbose=False)

    best_box = None
    largest_area = 0

    for box in results[0].boxes:

        cls = int(box.cls[0])

        # Person class
        if cls != 0:
            continue

        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()

        area = (x2 - x1) * (y2 - y1)

        if area > largest_area:
            largest_area = area
            best_box = (x1, y1, x2, y2)

    # ----------------------------------------
    # Update camera target
    # ----------------------------------------

    if best_box is not None:

        x1, y1, x2, y2 = best_box

        target_x = int((x1 + x2) / 2)
        target_y = int((y1 + y2) / 2)

        camera_x = int(
            SMOOTHING * camera_x +
            (1 - SMOOTHING) * target_x
        )

        camera_y = int(
            SMOOTHING * camera_y +
            (1 - SMOOTHING) * target_y
        )

    # ----------------------------------------
    # Calculate crop window
    # ----------------------------------------

    left = camera_x - crop_width // 2
    top = camera_y - crop_height // 2

    # Clamp inside image

    left = max(0, left)
    top = max(0, top)

    if left + crop_width > frame_width:
        left = frame_width - crop_width

    if top + crop_height > frame_height:
        top = frame_height - crop_height

    right = left + crop_width
    bottom = top + crop_height

    # ----------------------------------------
    # Crop
    # ----------------------------------------

    crop = frame[top:bottom, left:right]

    # ----------------------------------------
    # Resize
    # ----------------------------------------

    output = cv2.resize(
        crop,
        (OUTPUT_WIDTH, OUTPUT_HEIGHT),
        interpolation=cv2.INTER_LINEAR
    )

    writer.write(output)

    if frame_count % 30 == 0:
        print("Processed", frame_count, "frames")

# =====================================================
# CLEANUP
# =====================================================

cap.release()
writer.release()

print("Encoding H.264 and copying audio...")

cmd = [
    "ffmpeg",
    "-y",
    "-i", TEMP_VIDEO,
    "-i", INPUT_VIDEO,
    "-map", "0:v:0",
    "-map", "1:a?",
    "-c:v", "libx264",      # RTX GPU
    "-pix_fmt", "yuv420p",
    "-c:a", "copy",
    "-movflags", "+faststart",
    OUTPUT_VIDEO
]

subprocess.run(cmd, check=True)

os.remove(TEMP_VIDEO)

print("Done!")