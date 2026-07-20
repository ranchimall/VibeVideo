import os
import subprocess
from difflib import SequenceMatcher
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ── Lazy EasyOCR singleton ─────────────────────────────────────────────────────
_reader = None

def get_reader():
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(['en'], gpu=True)
    return _reader

# ── Audio helpers ──────────────────────────────────────────────────────────────
def extract_audio(input_file, audio_file, ffmpeg_path="ffmpeg"):
    # Re-encode to AAC so it works regardless of source audio codec
    cmd = f'"{ffmpeg_path}" -y -i "{input_file}" -vn -c:a aac -b:a 192k "{audio_file}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        # No audio stream or unsupported codec — silent fail is OK
        pass

# ── Font sizing ────────────────────────────────────────────────────────────────
def get_best_font(draw, text, target_w, target_h):
    font_path = None
    for candidate in ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"]:
        try:
            ImageFont.truetype(candidate, 10)
            font_path = candidate
            break
        except IOError:
            continue
    if font_path is None:
        return ImageFont.load_default()
    lo, hi, best = 1, 500, ImageFont.load_default()
    while lo <= hi:
        mid = (lo + hi) // 2
        f = ImageFont.truetype(font_path, mid)
        bb = draw.textbbox((0, 0), text, font=f)
        if (bb[2] - bb[0]) <= target_w and (bb[3] - bb[1]) <= target_h:
            best = f
            lo = mid + 1
        else:
            hi = mid - 1
    return best

# ── Color extraction ───────────────────────────────────────────────────────────
def extract_text_color(frame_bgr, box):
    xs = [int(p[0]) for p in box]
    ys = [int(p[1]) for p in box]
    x1 = max(0, min(xs));  x2 = min(frame_bgr.shape[1], max(xs))
    y1 = max(0, min(ys));  y2 = min(frame_bgr.shape[0], max(ys))
    roi = frame_bgr[y1:y2, x1:x2]
    if roi.size == 0:
        return (255, 255, 255)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    border = np.concatenate([thresh[0,:], thresh[-1,:], thresh[:,0], thresh[:,-1]])
    bg_val = 255 if np.mean(border) > 127 else 0
    text_mask = thresh != bg_val
    if not np.any(text_mask):
        return (255, 255, 255)
    avg_bgr = np.mean(roi[text_mask], axis=0)
    return (int(avg_bgr[2]), int(avg_bgr[1]), int(avg_bgr[0]))

# ── Text matching ──────────────────────────────────────────────────────────────
def fuzzy_match(ocr_text: str, target: str, threshold: float = 0.80) -> bool:
    """
    Match OCR output to target, robust to single-character drops/substitutions.
    Uses SequenceMatcher (handles 'The  LOBlockchain' → 'TheFLOBlockchain' perfectly).
    """
    a = ocr_text.lower().replace(" ", "")
    b = target.lower().replace(" ", "")
    if not a or not b:
        return False
    # Exact substring hit, but ONLY if it's a substantial chunk (at least 75% of target)
    if (b in a or a in b) and min(len(a), len(b)) >= len(b) * 0.75:
        return True
    # SequenceMatcher ratio — handles char drops far better than trigrams
    ratio = SequenceMatcher(None, a, b).ratio()
    return ratio >= threshold

# ── Box helpers ────────────────────────────────────────────────────────────────
def box_to_corners(box):
    """Return box as numpy float32 array of shape (4,1,2) for optical flow."""
    return np.array([[p] for p in box], dtype=np.float32)

def corners_to_box(corners):
    """Convert (4,1,2) corners back to [[x,y], ...] list."""
    return [[int(c[0][0]), int(c[0][1])] for c in corners]

# ── Optical-flow tracker ───────────────────────────────────────────────────────
LK_PARAMS = dict(
    winSize=(21, 21),
    maxLevel=3,
    criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
)

def track_box_lk(prev_gray, curr_gray, box):
    """
    Track 4 corner points from prev_gray → curr_gray using Lucas-Kanade.
    Returns new box or None if tracking fails.
    """
    pts = box_to_corners(box)
    new_pts, status, _ = cv2.calcOpticalFlowPyrLK(prev_gray, curr_gray, pts, None, **LK_PARAMS)
    if new_pts is None or status is None:
        return None
    good = status.flatten()
    if good.sum() < 3:          # need at least 3 of 4 corners tracked
        return None
    new_box = []
    for i, (npt, ok) in enumerate(zip(new_pts, good)):
        if ok:
            new_box.append([int(npt[0][0]), int(npt[0][1])])
        else:
            new_box.append(box[i])  # fallback: keep old corner
    return new_box

# ── Per-frame composer ─────────────────────────────────────────────────────────
def compose_frame(frame_bgr, box, new_text, frame_w, frame_h, cached_color=None):
    xs = [p[0] for p in box];  ys = [p[1] for p in box]
    x = max(0, min(xs));       y = max(0, min(ys))
    w = max(1, max(xs) - x);   h = max(1, max(ys) - y)

    text_color = cached_color if cached_color else extract_text_color(frame_bgr, box)

    pad_x = max(8, int(w * 0.15))
    pad_y = max(8, int(h * 0.20))
    x1 = max(0, x - pad_x);       y1 = max(0, y - pad_y)
    x2 = min(frame_w, x+w+pad_x); y2 = min(frame_h, y+h+pad_y)

    mask = np.zeros((frame_h, frame_w), dtype=np.uint8)
    roi = frame_bgr[y1:y2, x1:x2]
    if roi.size > 0:
        gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray_roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        border = np.concatenate([thresh[0,:], thresh[-1,:], thresh[:,0], thresh[:,-1]])
        bg_val = 255 if np.mean(border) > 127 else 0
        text_mask = thresh if bg_val == 0 else cv2.bitwise_not(thresh)
        
        kernel = np.ones((5,5), np.uint8)
        text_mask = cv2.dilate(text_mask, kernel, iterations=1)
        
        mask[y1:y2, x1:x2] = text_mask
    else:
        cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)

    inpainted = cv2.inpaint(frame_bgr, mask, 3, cv2.INPAINT_TELEA)

    img_pil = Image.fromarray(cv2.cvtColor(inpainted, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    font = get_best_font(draw, new_text, w, h)
    bb = draw.textbbox((0, 0), new_text, font=font)
    tw, th = bb[2]-bb[0], bb[3]-bb[1]
    cx = x + w//2 - tw//2
    cy = y + h//2 - th//2

    shadow = tuple(max(0, c - 80) for c in text_color)
    for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]:
        draw.text((cx+dx, cy+dy), new_text, font=font, fill=shadow)
    draw.text((cx, cy), new_text, font=font, fill=text_color)

    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

# ── Main pipeline (two-pass + optical-flow tracking) ──────────────────────────
def run_pipeline(instruction, ffmpeg_path="ffmpeg"):
    inp      = instruction.get("input", {})
    out_dict = instruction.get("output", {})

    input_files = inp.get("input_files", [])
    if not input_files:
        raise ValueError("No input files provided.")

    video_path  = input_files[0]
    output_file = out_dict.get("output_file") or "replaced_output.mp4"
    old_text    = inp.get("old_text", "").strip()
    new_text    = inp.get("new_text", "").strip()

    if not old_text or not new_text:
        raise ValueError("Missing old_text or new_text.")

    print(f"\n[CV Engine] Replacing '{old_text}' -> '{new_text}' in {video_path}")
    print("[CV Engine] Loading EasyOCR...")
    reader = get_reader()

    cap = cv2.VideoCapture(video_path)
    fps          = cap.get(cv2.CAP_PROP_FPS) or 30
    frame_w      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h      = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"[CV Engine] Pass 1/2 — OCR + optical-flow tracking ({total_frames} frames)...")

    # ── Pass 1: build per-frame box map using OCR + LK tracking ──────────────
    # OCR every 30 frames = just for long-term drift prevention.
    # LK optical flow handles smooth frame-by-frame tracking in between.
    # This eliminates the OCR-snap jitter caused by frequent re-anchoring.
    OCR_EVERY  = 30
    MAX_MISSED = 8   # consecutive OCR misses before marking text as gone

    all_boxes   = {}         # frame_idx → box | None
    text_color  = None       # sampled once when text first found

    current_box  = None
    prev_gray    = None
    prev_hist    = None      # for scene-change detection
    missed_ocr   = 0         # consecutive OCR frames where target not found
    frames_since_scene = 0 # frames elapsed since last scene change

    frame_buffer = []
    MAX_BUFFER = OCR_EVERY + 5

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # ── Scene change detection via grayscale histogram correlation ──────
        hist = cv2.calcHist([gray], [0], None, [64], [0, 256])
        cv2.normalize(hist, hist)
        scene_changed = False
        if prev_hist is not None:
            corr = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
            if corr < 0.75:   # dramatic change in brightness distribution
                scene_changed = True
                current_box = None
                missed_ocr  = 0
                frames_since_scene = 0
                frame_buffer.clear()
        prev_hist = hist
        
        frame_buffer.append((frame_idx, gray))
        if len(frame_buffer) > MAX_BUFFER:
            frame_buffer.pop(0)
        
        if not scene_changed:
            frames_since_scene += 1

        # ── Always run OCR every OCR_EVERY frames, OR very frequently 
        # (every 5 frames) right after a scene change to catch fade-ins ──
        high_freq_scan = (frames_since_scene < 45 and frame_idx % 5 == 0)
        run_ocr = (frame_idx % OCR_EVERY == 0) or scene_changed or high_freq_scan

        if run_ocr:
            results = reader.readtext(frame)
            found = None
            candidates = [
                (bbox, txt, prob) for (bbox, txt, prob) in results
                if prob >= 0.35 and fuzzy_match(txt, old_text)
            ]
            candidates.sort(key=lambda x: -x[2])
            for (bbox, txt, prob) in candidates:
                pts = [list(map(int, p)) for p in bbox]
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                area = (max(xs) - min(xs)) * (max(ys) - min(ys))
                if area < frame_w * frame_h * 0.003:
                    continue
                found = pts
                if text_color is None:
                    text_color = extract_text_color(frame, found)
                break

            if found is not None:
                if current_box is None and len(frame_buffer) > 1:
                    # ── Text newly found! Track backwards to catch fade-ins ──
                    box_back = found
                    for b_i in range(len(frame_buffer)-1, 0, -1):
                        curr_f_idx, curr_g = frame_buffer[b_i]
                        prev_f_idx, prev_g = frame_buffer[b_i-1]
                        
                        tracked_back = track_box_lk(curr_g, prev_g, box_back)
                        if tracked_back is not None:
                            box_back = tracked_back
                            all_boxes[prev_f_idx] = box_back
                        else:
                            break

                current_box = found
                missed_ocr  = 0
                frames_since_scene = 999  # text found, stop high-frequency scan
            else:
                missed_ocr += 1
                if missed_ocr >= MAX_MISSED:
                    current_box = None   # text genuinely gone — stop drawing

        elif current_box is not None and prev_gray is not None:
            # Between OCR anchors: use Lucas-Kanade optical flow
            # LK gives sub-pixel smooth motion that perfectly matches the logo
            tracked = track_box_lk(prev_gray, gray, current_box)
            if tracked is not None:
                # Exponential moving average (alpha=0.7) to dampen LK micro-noise
                alpha = 0.7
                smoothed = [
                    [int(alpha * tracked[i][0] + (1 - alpha) * current_box[i][0]),
                     int(alpha * tracked[i][1] + (1 - alpha) * current_box[i][1])]
                    for i in range(4)
                ]
                current_box = smoothed

        all_boxes[frame_idx] = current_box

        prev_gray = gray
        frame_idx += 1

        if frame_idx % 30 == 0:
            status = "tracking" if current_box else "no text"
            print(f"[CV Engine]  scan  {frame_idx}/{total_frames}  [{status}]")

    cap.release()

    # ── Temporal smoothing: moving average with window=15 across all frames ───
    # Eliminates residual jitter from OCR re-anchoring every 30 frames.
    # We group by contiguous frame segments to avoid smoothing across scene cuts.
    sorted_idxs = sorted([idx for idx, b in all_boxes.items() if b is not None])
    
    if sorted_idxs:
        # Group into continuous segments
        segments = []
        current_segment = [sorted_idxs[0]]
        for idx in sorted_idxs[1:]:
            if idx == current_segment[-1] + 1:
                current_segment.append(idx)
            else:
                segments.append(current_segment)
                current_segment = [idx]
        segments.append(current_segment)

        for segment in segments:
            if len(segment) < 3:
                continue
            for corner in range(4):
                for coord in range(2):   # 0=x, 1=y
                    vals = [all_boxes[idx][corner][coord] for idx in segment]
                    
                    window = 15
                    smoothed = []
                    for i in range(len(vals)):
                        lo = max(0, i - window // 2)
                        hi = min(len(vals), i + window // 2 + 1)
                        smoothed.append(int(sum(vals[lo:hi]) / (hi - lo)))

                    for i, idx in enumerate(segment):
                        all_boxes[idx][corner][coord] = smoothed[i]

    # ── Pass 2: render ─────────────────────────────────────────────────────────
    print("[CV Engine] Pass 2/2 — Rendering frames...")

    temp_video = "_cv_tmp_video.mp4"
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(temp_video, fourcc, fps, (frame_w, frame_h))

    cap2 = cv2.VideoCapture(video_path)
    frame_idx = 0
    while True:
        ret, frame = cap2.read()
        if not ret:
            break

        box = all_boxes.get(frame_idx)
        if box is not None:
            frame = compose_frame(frame, box, new_text, frame_w, frame_h, text_color)

        writer.write(frame)

        if frame_idx % 30 == 0 and frame_idx > 0:
            print(f"[CV Engine]  render {frame_idx}/{total_frames}")

        frame_idx += 1

    cap2.release()
    writer.release()

    # ── Merge audio ────────────────────────────────────────────────────────────
    print("[CV Engine] Merging audio...")
    temp_audio = "_cv_tmp_audio.aac"
    extract_audio(video_path, temp_audio, ffmpeg_path)

    if os.path.exists(temp_audio) and os.path.getsize(temp_audio) > 0:
        merge_cmd = (
            f'"{ffmpeg_path}" -y -i "{temp_video}" -i "{temp_audio}" '
            f'-c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p -c:a aac -b:a 192k "{output_file}"'
        )
    else:
        merge_cmd = (
            f'"{ffmpeg_path}" -y -i "{temp_video}" '
            f'-c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p "{output_file}"'
        )

    result = subprocess.run(merge_cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[CV Engine] WARNING: FFmpeg merge failed:\n{result.stderr[-500:]}")
        # If merge fails, at least save the video without audio so it's not lost
        import shutil
        shutil.copy(temp_video, output_file)

    for f in [temp_video, temp_audio]:
        if os.path.exists(f):
            try: os.remove(f)
            except: pass

    print(f"[CV Engine] Done! Saved to {output_file}")
    return output_file

# ── Engine dispatcher ──────────────────────────────────────────────────────────
def execute_cv(implementation, instruction):
    import imageio_ffmpeg
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    if implementation == "video_replace_text":
        return run_pipeline(instruction, ffmpeg_path)
    raise ValueError(f"Unknown CV implementation: {implementation}")
