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
            # Use the large segmentation model for high accuracy detection and pixel-perfect masks
            _yolo_model = YOLO('yolo11l-seg.pt')
        except ImportError:
            raise ImportError("Please install ultralytics: pip install ultralytics")
    return _yolo_model

def extract_audio(input_file, audio_file, ffmpeg_path="ffmpeg"):
    cmd = [ffmpeg_path, "-y", "-i", input_file, "-vn", "-c:a", "aac", "-b:a", "192k", audio_file]
    subprocess.run(cmd, capture_output=True, text=True)

def overlay_image(background_bgr, foreground_pil, x, y, w, h, obj_mask=None, preserve_aspect=True, feather_px=5):
    """Overlay a PIL image with transparency onto an OpenCV BGR frame.

    - preserve_aspect: fit the replacement inside the (w, h) box without stretching,
      centering it, instead of distorting it to exactly fill the bbox.
    - obj_mask: optional full-frame uint8 mask (0/255) of the object's segmentation
      shape. When given, the replacement is additionally clipped to that silhouette
      (feathered) so it doesn't sit as an obvious rectangle over a round/irregular object.
    """
    fg_rgba = foreground_pil.convert("RGBA")

    if preserve_aspect:
        fg_w, fg_h = fg_rgba.size
        scale = min(w / fg_w, h / fg_h)
        new_w, new_h = max(1, int(fg_w * scale)), max(1, int(fg_h * scale))
        fg_rgba = fg_rgba.resize((new_w, new_h), Image.Resampling.LANCZOS)
        paste_x = int(x + (w - new_w) / 2)
        paste_y = int(y + (h - new_h) / 2)
    else:
        fg_rgba = fg_rgba.resize((int(w), int(h)), Image.Resampling.LANCZOS)
        paste_x, paste_y = int(x), int(y)
        new_w, new_h = int(w), int(h)

    # Build an alpha layer the size of the full frame so we can combine the
    # replacement's own transparency with the object's segmentation silhouette.
    frame_h, frame_w = background_bgr.shape[:2]
    fg_rgb_np = np.array(fg_rgba.convert("RGB"))
    fg_alpha_np = np.array(fg_rgba.getchannel("A"))

    full_rgb = np.zeros((frame_h, frame_w, 3), dtype=np.uint8)
    full_alpha = np.zeros((frame_h, frame_w), dtype=np.uint8)

    x0, y0 = max(0, paste_x), max(0, paste_y)
    x1, y1 = min(frame_w, paste_x + new_w), min(frame_h, paste_y + new_h)
    if x1 <= x0 or y1 <= y0:
        return background_bgr  # fully out of frame, nothing to do

    src_x0, src_y0 = x0 - paste_x, y0 - paste_y
    src_x1, src_y1 = src_x0 + (x1 - x0), src_y0 + (y1 - y0)

    full_rgb[y0:y1, x0:x1] = fg_rgb_np[src_y0:src_y1, src_x0:src_x1]
    full_alpha[y0:y1, x0:x1] = fg_alpha_np[src_y0:src_y1, src_x0:src_x1]

    if obj_mask is not None:
        # Clip the replacement to the object's actual silhouette so it follows
        # the object's outline instead of sitting as a hard rectangle.
        full_alpha = cv2.bitwise_and(full_alpha, obj_mask)

    if feather_px > 0:
        k = feather_px * 2 + 1
        full_alpha = cv2.GaussianBlur(full_alpha, (k, k), 0)

    alpha_f = (full_alpha.astype(np.float32) / 255.0)[..., None]
    full_rgb_bgr = cv2.cvtColor(full_rgb, cv2.COLOR_RGB2BGR)
    blended = (full_rgb_bgr.astype(np.float32) * alpha_f +
               background_bgr.astype(np.float32) * (1 - alpha_f))
    return blended.astype(np.uint8)

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
    print("[CV Object Engine] Loading YOLO11 Segmentation...")
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
    last_valid_seg_mask = None
    missing_frames = 0
    smooth_bbox = None          # explicit state instead of relying on locals()
    locked_track_id = None      # the specific object instance we're following
    prev_mask_f = None          # previous frame's mask (float, full-frame) for temporal blending
    prev_mask_center = None     # centroid of that previous mask, to detect large jumps

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
        seg_mask = None

        # Use ByteTrack (via Ultralytics' built-in tracker) instead of a fresh
        # detect-only pass. This assigns a persistent track_id to each object,
        # so once we lock onto the right instance we keep following THAT one
        # rather than re-picking "whichever box has highest confidence" every
        # frame, which is what let the target flicker between two objects
        # of the same class (e.g. two cars) in the original version.
        results = model.track(frame, persist=True, verbose=False, tracker="bytetrack.yaml")

        candidates = []  # (track_id, conf, bbox, seg_mask)
        for result in results:
            if result.boxes is None or result.masks is None:
                continue
            ids = result.boxes.id
            for i, box in enumerate(result.boxes):
                cls_id = int(box.cls[0])
                class_name = model.names[cls_id].lower()
                if target_object not in class_name:
                    continue
                conf = float(box.conf[0])
                track_id = int(ids[i]) if ids is not None else None
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                cand_bbox = (int(x1), int(y1), int(x2 - x1), int(y2 - y1))
                cand_mask = result.masks.data[i].cpu().numpy()
                candidates.append((track_id, conf, cand_bbox, cand_mask))

        if candidates:
            if locked_track_id is not None:
                # Prefer to keep following the same tracked instance.
                match = next((c for c in candidates if c[0] == locked_track_id), None)
            else:
                match = None

            if match is None:
                # First sighting, or the locked ID temporarily disappeared and
                # was reassigned (ByteTrack can drop/re-add IDs) — fall back to
                # the highest-confidence candidate and (re)lock onto its ID.
                match = max(candidates, key=lambda c: c[1])

            locked_track_id, _, bbox, seg_mask = match

        if bbox is None:
            if frame_idx == 1:
                print(f"[CV Object Engine] Could not find '{target_object}' in the first frame.")
            elif last_valid_bbox is not None and missing_frames < 10:
                # Lost track for a moment — hold the last known position/mask so it doesn't blink.
                bbox = last_valid_bbox
                seg_mask = last_valid_seg_mask
                missing_frames += 1
            else:
                # Missing too long — assume it left frame, and drop the lock so
                # we don't keep waiting on a track_id that's gone for good.
                last_valid_bbox = None
                last_valid_seg_mask = None
                locked_track_id = None
                smooth_bbox = None
                prev_mask_f = None
                prev_mask_center = None
        else:
            last_valid_bbox = bbox
            last_valid_seg_mask = seg_mask
            missing_frames = 0

        # If we have a detection, smooth the bbox and do the replacement
        if bbox is not None:
            if smooth_bbox is None:
                # First time seeing the object (or just reacquired after being lost) —
                # trust YOLO's raw guess for now rather than blending from a stale position.
                smooth_bbox = [float(v) for v in bbox]
            else:
                # EMA smoothing so the box glides instead of jittering frame to frame.
                alpha = 0.3
                for i in range(4):
                    smooth_bbox[i] = alpha * bbox[i] + (1 - alpha) * smooth_bbox[i]

            x, y, w, h = [int(v) for v in smooth_bbox]

            # Clamp to frame edges
            x = max(0, x); y = max(0, y)
            w = min(frame_w - x, w); h = min(frame_h - y, h)

            if w > 0 and h > 0:
                # Build the raw mask — use the pixel-perfect segmentation mask if we have one,
                # otherwise fall back to a plain rectangle (better than nothing)
                if seg_mask is not None:
                    # YOLO's seg mask comes at model resolution, resize it to match the actual frame
                    raw_mask = cv2.resize(seg_mask, (frame_w, frame_h), interpolation=cv2.INTER_NEAREST)
                    raw_mask = (raw_mask > 0.5).astype(np.uint8) * 255
                else:
                    raw_mask = np.zeros((frame_h, frame_w), dtype=np.uint8)
                    cv2.rectangle(raw_mask, (x, y), (x + w, y + h), 255, -1)

                # Temporal smoothing of the mask itself: blend with the previous
                # frame's mask so the inpaint/overlay silhouette doesn't flicker
                # even when the bbox is roughly stationary. But if the object has
                # moved a lot since the last frame (fast motion, e.g. drone/aerial
                # footage), the previous mask sits at a completely different
                # spot — blending two masks at different locations doesn't smooth
                # anything, it creates a double-exposure "ghost" trail that gets
                # partially inpainted gray. So only blend when the object's
                # centroid hasn't moved far relative to its own size.
                cur_center = (x + w / 2.0, y + h / 2.0)
                moved_too_far = True
                if prev_mask_center is not None:
                    dist = ((cur_center[0] - prev_mask_center[0]) ** 2 +
                            (cur_center[1] - prev_mask_center[1]) ** 2) ** 0.5
                    moved_too_far = dist > 0.5 * max(w, h)

                raw_mask_f = raw_mask.astype(np.float32)
                if prev_mask_f is not None and not moved_too_far:
                    blended_mask_f = 0.5 * raw_mask_f + 0.5 * prev_mask_f
                else:
                    blended_mask_f = raw_mask_f
                prev_mask_f = blended_mask_f
                prev_mask_center = cur_center
                mask = (blended_mask_f > 127).astype(np.uint8) * 255

                # Pad relative to object size (with a floor) instead of a flat
                # kernel, so small objects don't get over-eaten and large ones
                # don't keep a visible fringe.
                pad = max(11, int(0.03 * max(w, h)))
                if pad % 2 == 0:
                    pad += 1
                kernel = np.ones((pad, pad), np.uint8)
                inpaint_mask = cv2.dilate(mask, kernel, iterations=1)

                inpainted_frame = cv2.inpaint(frame, inpaint_mask, 7, cv2.INPAINT_TELEA)

                # Overlay replacement image on top of the erased spot, clipped to
                # the object's silhouette (not just the bbox rectangle) and
                # feathered at the edges, preserving the replacement's own aspect ratio.
                if replacement_img:
                    frame = overlay_image(
                        inpainted_frame, replacement_img, x, y, w, h,
                        obj_mask=mask, preserve_aspect=True, feather_px=5
                    )
                else:
                    frame = inpainted_frame

        out.write(frame)
        
    cap.release()
    out.release()
    
    print("[CV Object Engine] Multiplexing audio and encoding to H.264...")
    if os.path.exists(temp_audio):
        cmd = [ffmpeg_path, "-y", "-i", temp_video, "-i", temp_audio,
               "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0?", output_file]
    else:
        cmd = [ffmpeg_path, "-y", "-i", temp_video,
               "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", output_file]

    subprocess.run(cmd, capture_output=True)
    
    if os.path.exists(temp_audio): os.remove(temp_audio)
    if os.path.exists(temp_video): os.remove(temp_video)
    
    print(f"[CV Object Engine] Done! Saved to {output_file}")
    return output_file