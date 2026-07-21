import os
import subprocess
import cv2
import numpy as np
from PIL import Image

_yolo_model = None

def get_yolo_model():
    global _yolo_model
    if _yolo_model is None:
        try:
            from ultralytics import YOLO
            # yolo11n is lightweight and fast
            _yolo_model = YOLO('yolo11n.pt')
        except ImportError:
            raise ImportError("Please install ultralytics: pip install ultralytics")
    return _yolo_model

def extract_audio(input_file, audio_file, ffmpeg_path="ffmpeg"):
    cmd = f'"{ffmpeg_path}" -y -i "{input_file}" -vn -c:a aac -b:a 192k "{audio_file}"'
    subprocess.run(cmd, shell=True, capture_output=True, text=True)

def overlay_image(background_bgr, foreground_pil, x, y):
    """Overlay a PIL image with transparency onto an OpenCV BGR frame."""
    bg_pil = Image.fromarray(cv2.cvtColor(background_bgr, cv2.COLOR_BGR2RGB))
    # Make sure foreground is RGBA
    fg_rgba = foreground_pil.convert("RGBA")
    
    # Paste using alpha channel as mask
    bg_pil.paste(fg_rgba, (int(x), int(y)), fg_rgba)
    return cv2.cvtColor(np.array(bg_pil), cv2.COLOR_RGB2BGR)

def execute_cv_object(instruction, ffmpeg_path="ffmpeg"):
    inp = instruction.get("input", {})
    out_dict = instruction.get("output", {})
    
    input_files = inp.get("input_files", [])
    if len(input_files) < 1:
        raise ValueError("At least one input video is required.")
        
    video_path = input_files[0]
    replacement_path = input_files[1] if len(input_files) > 1 else None
    
    output_file = out_dict.get("output_file") or "replaced_output.mp4"
    target_object = inp.get("target_object", "").strip().lower()
    
    if not target_object:
        raise ValueError("Missing target_object to replace (e.g., 'car', 'person').")
        
    print(f"\n[CV Object Engine] Replacing '{target_object}' in {video_path}")
    print("[CV Object Engine] Loading YOLO11...")
    model = get_yolo_model()
    
    # Load replacement image if provided
    replacement_img = None
    if replacement_path and os.path.exists(replacement_path):
        replacement_img = Image.open(replacement_path)
    else:
        print("[CV Object Engine] No replacement image provided or found. Will just inpaint (remove).")

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    temp_audio = "temp_audio.m4a"
    temp_video = "temp_video_no_audio.mp4"
    
    extract_audio(video_path, temp_audio, ffmpeg_path)
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(temp_video, fourcc, fps, (frame_w, frame_h))
    
    last_valid_bbox = None
    
    print(f"[CV Object Engine] Processing {total_frames} frames...")
    
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        frame_idx += 1
        if frame_idx % 30 == 0:
            print(f"  Processed {frame_idx}/{total_frames} frames...")
            
        bbox = None
        
        # Find object in the current frame using YOLO
        results = model(frame, verbose=False)
        best_conf = 0
        
        for result in results:
            boxes = result.boxes
            for box in boxes:
                cls_id = int(box.cls[0])
                class_name = model.names[cls_id].lower()
                conf = float(box.conf[0])
                
                if target_object in class_name and conf > best_conf:
                    best_conf = conf
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    bbox = (int(x1), int(y1), int(x2-x1), int(y2-y1))
        
        if bbox is None:
            if frame_idx == 1:
                print(f"[CV Object Engine] Could not find '{target_object}' in the first frame.")
            elif last_valid_bbox is not None:
                # YOLO lost the object for a sec! Quick, pretend we still see it exactly where it was so it doesn't blink!
                bbox = last_valid_bbox
        else:
            last_valid_bbox = bbox
                
        # If we have a bounding box, smooth it and do replacement
        if bbox is not None:
            # First time seeing the object? Just trust YOLO's raw guess for now
            if 'smooth_bbox' not in locals():
                smooth_bbox = [float(v) for v in bbox]
            else:
                # YOLO jitters worse than I do after 3 cups of coffee. Use an Exponential Moving Average to make it glide like butter.
                alpha = 0.3
                for i in range(4):
                    smooth_bbox[i] = alpha * bbox[i] + (1 - alpha) * smooth_bbox[i]
            
            x, y, w, h = [int(v) for v in smooth_bbox]
            
            # Clamp to frame edges
            x = max(0, x); y = max(0, y)
            w = min(frame_w - x, w); h = min(frame_h - y, h)
            
            if w > 0 and h > 0:
                # 1. Inpaint
                mask = np.zeros((frame_h, frame_w), dtype=np.uint8)
                cv2.rectangle(mask, (x, y), (x+w, y+h), 255, -1)
                
                # Erase a massive chunk around the object so we don't accidentally smear its edges into a creepy ghost smudge
                kernel = np.ones((21, 21), np.uint8)
                mask = cv2.dilate(mask, kernel, iterations=2)
                
                inpainted_frame = cv2.inpaint(frame, mask, 7, cv2.INPAINT_TELEA)
                
                # 2. Overlay replacement
                if replacement_img:
                    # Resize replacement to fit the box
                    resized_repl = replacement_img.resize((w, h), Image.Resampling.LANCZOS)
                    frame = overlay_image(inpainted_frame, resized_repl, x, y)
                else:
                    frame = inpainted_frame
                    
        out.write(frame)
        
    cap.release()
    out.release()
    
    print("[CV Object Engine] Multiplexing audio and encoding to H.264...")
    if os.path.exists(temp_audio):
        cmd = f'"{ffmpeg_path}" -y -i "{temp_video}" -i "{temp_audio}" -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p -c:a aac -map 0:v:0 -map 1:a:0? "{output_file}"'
    else:
        cmd = f'"{ffmpeg_path}" -y -i "{temp_video}" -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p "{output_file}"'
        
    subprocess.run(cmd, shell=True, capture_output=True)
    
    if os.path.exists(temp_audio): os.remove(temp_audio)
    if os.path.exists(temp_video): os.remove(temp_video)
    
    print(f"[CV Object Engine] Done! Saved to {output_file}")
    return output_file
