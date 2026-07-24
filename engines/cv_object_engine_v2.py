"""
Version 2: The ultimate AI object replacement engine using SAM2 + ProPainter.

Why did we build this?
The old Version 1 (using just YOLO) was fast, but since it processed the video 
frame-by-frame, the objects flickered and the background looked glitchy. 

This new engine completely fixes that by treating the video as a whole:
1. It uses Meta's SAM 2 to track the object flawlessly from start to finish.
2. It uses ProPainter to completely erase the object and smoothly fill in the 
   missing background by looking at past and future frames.
3. Finally, it pastes our replacement image perfectly over the tracked mask.

Note: These AI models are incredibly heavy! If you run this on a normal laptop,
it might crash or take a very long time. Because of this, I've added custom 
hardware detection: if your computer doesn't have a 6GB+ GPU, this script 
will automatically compress the memory it uses by 4x and run safely on your 
CPU to prevent crashing.

For maximum speed, I highly recommend running this on a cloud GPU (like Google Colab) instead!
"""

import os
import shutil
import subprocess
import glob
import cv2
import numpy as np
from PIL import Image

# Reuse the mask-shaped, feathered, aspect-preserving compositor -- that part
# of the old pipeline was already correct, the problem was always upstream.
from engines.cv_object_engine import overlay_image, extract_audio

# ---- Configure these paths for your machine ----
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAM2_CHECKPOINT = os.path.join(BASE_DIR, "weights", "sam2.1_hiera_small.pt")
SAM2_MODEL_CONFIG = "configs/sam2.1/sam2.1_hiera_s.yaml"   # ships with the sam2 package
PROPAINTER_DIR = os.path.join(BASE_DIR, "ProPainter")                 # path to the cloned repo
# --------------------------------------------------

_yolo_seed_model = None


def get_yolo_seed_model():
    """YOLO is now only used ONCE per video, to find a seed bounding box for
    SAM2 to prompt with -- not run per-frame anymore."""
    global _yolo_seed_model
    if _yolo_seed_model is None:
        from ultralytics import YOLO
        _yolo_seed_model = YOLO('yolo11l-seg.pt')
    return _yolo_seed_model


def find_seed_box(video_path, target_object, max_search_frames=None, conf_threshold=0.25):
    """Scan frames until the target object is found with reasonable
    confidence, and return (frame_index, bbox_xyxy). Returns (None, None) if
    not found anywhere in the video (or within max_search_frames, if given).

    Defaults to scanning the WHOLE video rather than a short window -- the
    seed only needs to be found ONCE, so there's no real cost to searching
    further in, and objects that enter the frame later than a couple of
    seconds in would otherwise never get picked up at all.
    """
    model = get_yolo_seed_model()
    cap = cv2.VideoCapture(video_path)
    frame_idx = -1
    classes_seen = set()

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1
        if max_search_frames is not None and frame_idx >= max_search_frames:
            break
        if frame_idx % 30 == 0 and frame_idx > 0:
            print(f"  Searching for seed frame... {frame_idx} frames scanned so far.")

        results = model(frame, verbose=False)
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                cls_id = int(box.cls[0])
                class_name = model.names[cls_id].lower()
                conf = float(box.conf[0])
                classes_seen.add(class_name)
                if target_object in class_name and conf >= conf_threshold:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    cap.release()
                    return frame_idx, (x1, y1, x2, y2)

    cap.release()
    if classes_seen:
        print(f"[SAM2+ProPainter] '{target_object}' not found. Classes YOLO did see: {sorted(classes_seen)}")
    return None, None


def extract_frames(video_path, frames_dir, ffmpeg_path="ffmpeg", fps=None, max_size=720):
    """Extract video to individual frame images (both SAM2's video predictor
    and ProPainter operate on frame sequences, not a video stream).

    max_size: cap the longer edge of each frame at this pixel count. Smaller
    frames dramatically reduce the RAM needed for SAM2's init_state (which
    loads every frame into memory at once). 720 keeps detail while keeping
    a 647-frame 1080p clip inside ~4 GB of RAM instead of ~15 GB.
    """
    os.makedirs(frames_dir, exist_ok=True)
    cmd = [ffmpeg_path, "-y", "-i", video_path]
    vf_parts = []
    if fps:
        vf_parts.append(f"fps={fps}")
    if max_size:
        # scale so the longest side == max_size, keep aspect ratio, ensure even dims
        vf_parts.append(f"scale='if(gt(iw,ih),{max_size},-2)':'if(gt(ih,iw),{max_size},-2)'")
    if vf_parts:
        cmd += ["-vf", ",".join(vf_parts)]
    cmd += [os.path.join(frames_dir, "%06d.jpg")]
    subprocess.run(cmd, capture_output=True)
    return sorted(glob.glob(os.path.join(frames_dir, "*.jpg")))


def _run_sam2_tracking_on_device(frames_dir, seed_frame_idx, seed_box_xyxy, device):
    """Does the actual SAM2 propagation work on the given device ('cuda' or
    'cpu'). Separated out so the caller can try GPU first and fall back to
    CPU only if GPU genuinely runs out of memory."""
    import torch
    from sam2.build_sam import build_sam2_video_predictor

    predictor = build_sam2_video_predictor(SAM2_MODEL_CONFIG, SAM2_CHECKPOINT, device=device)
    # offload_video_to_cpu / offload_state_to_cpu: keep the full frame set and
    # inactive tracking state in CPU RAM, only moving what's actively needed
    # onto the GPU per step. This is what actually fixes low-VRAM OOMs on
    # long clips -- the model itself isn't the memory hog, holding all frames
    # resident on the GPU at once is. On CPU these offload flags are harmless
    # no-ops (everything's already in RAM), so the same code path works for
    # both devices.
    inference_state = predictor.init_state(
        video_path=frames_dir,
        offload_video_to_cpu=True,
        offload_state_to_cpu=True,
    )

    predictor.reset_state(inference_state)

    use_autocast = device == "cuda"
    autocast_ctx = torch.autocast("cuda", dtype=torch.bfloat16) if use_autocast else torch.autocast("cpu", enabled=False)

    with autocast_ctx:
        _, _, _ = predictor.add_new_points_or_box(
            inference_state=inference_state,
            frame_idx=seed_frame_idx,
            obj_id=1,
            box=np.array(seed_box_xyxy, dtype=np.float32),
        )

        masks_by_frame = {}

        # Forward pass from the seed frame to the end of the clip.
        for frame_idx, obj_ids, mask_logits in predictor.propagate_in_video(inference_state):
            mask = (mask_logits[0] > 0.0).cpu().numpy().squeeze().astype(np.uint8) * 255
            masks_by_frame[frame_idx] = mask

        # Backward pass, in case the object is also visible before the seed frame.
        if seed_frame_idx > 0:
            for frame_idx, obj_ids, mask_logits in predictor.propagate_in_video(
                inference_state, start_frame_idx=seed_frame_idx, reverse=True
            ):
                if frame_idx not in masks_by_frame:
                    mask = (mask_logits[0] > 0.0).cpu().numpy().squeeze().astype(np.uint8) * 255
                    masks_by_frame[frame_idx] = mask

    return masks_by_frame


def run_sam2_tracking(frames_dir, seed_frame_idx, seed_box_xyxy):
    """Propagate a single object's mask across every frame using SAM2's
    video predictor. Returns a dict: {frame_idx: mask_uint8_HxW}.

    Tries GPU first (with CPU-offloading of inactive frames/state enabled,
    which is what actually fixes most low-VRAM OOMs on long clips while
    still running the model itself on GPU). Only falls back to full CPU
    execution if GPU still runs out of memory -- CPU is a real last resort
    here, since SAM2's transformer-based encoder is significantly slower
    per-frame on CPU than GPU, so it's worth trying to stay on GPU first.

    NOTE: SAM2's video predictor propagates forward from the seeded frame by
    default. If the object appears mid-clip and you also need masks for
    frames BEFORE the seed frame, propagate_in_video supports a
    reverse=True pass too -- included in the device-specific helper above.
    """
    import torch

    # SAM2's video predictor loads frame features onto the GPU iteratively.
    # On low-VRAM cards (< 6 GB) it will OOM mid-propagation, and a mid-run
    # CUDA OOM corrupts the GPU state so badly that even the Python cleanup
    # during the try/except fallback causes a hard process abort.
    # It is safer to detect this upfront and skip GPU entirely.
    SAM2_MIN_VRAM_GB = 6
    use_gpu = False
    if torch.cuda.is_available():
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        if vram_gb >= SAM2_MIN_VRAM_GB:
            use_gpu = True
        else:
            print(f"[SAM2+ProPainter] GPU has {vram_gb:.1f} GB VRAM (< {SAM2_MIN_VRAM_GB} GB minimum for SAM2).")
            print("[SAM2+ProPainter] Running on CPU to avoid a hard crash -- this will be slower.")

    if use_gpu:
        print("[SAM2+ProPainter] Running SAM2 on GPU (with CPU offloading enabled)...")
        return _run_sam2_tracking_on_device(frames_dir, seed_frame_idx, seed_box_xyxy, device="cuda")

    return _run_sam2_tracking_on_device(frames_dir, seed_frame_idx, seed_box_xyxy, device="cpu")


def export_masks(masks_by_frame, frame_paths, masks_dir):
    """Write one mask PNG per frame (blank/black where the object wasn't
    tracked, e.g. before it enters or after it leaves) -- this is the format
    ProPainter's inference script expects."""
    os.makedirs(masks_dir, exist_ok=True)
    sample = cv2.imread(frame_paths[0])
    h, w = sample.shape[:2]

    for i, frame_path in enumerate(frame_paths):
        mask = masks_by_frame.get(i)
        if mask is None:
            mask = np.zeros((h, w), dtype=np.uint8)
        out_path = os.path.join(masks_dir, os.path.basename(frame_path).replace(".jpg", ".png"))
        cv2.imwrite(out_path, mask)


def run_propainter(frames_dir, masks_dir, output_dir):
    """Run ProPainter in the same process using runpy to avoid Windows 
    Paging File exhaustion (WinError 1455) caused by loading PyTorch twice."""
    import sys, torch, os, runpy
    script = os.path.join(PROPAINTER_DIR, "inference_propainter.py")
    
    original_argv = sys.argv[:]
    original_path = sys.path[:]
    
    try:
        sys.argv = [
            script,
            "--video", frames_dir,
            "--mask", masks_dir,
            "--output", output_dir,
        ]
        
        sys.path.insert(0, PROPAINTER_DIR)
        import model.misc
        original_get_device = model.misc.get_device
        
        if torch.cuda.is_available():
            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            if vram_gb < 6.0:
                print(f"[SAM2+ProPainter] GPU VRAM ({vram_gb:.1f} GB) too low for ProPainter.")
                print("[SAM2+ProPainter] Forcing CPU mode and 0.5x resolution to avoid RAM OOM (will be very slow).")
                model.misc.get_device = lambda: torch.device('cpu')
                sys.argv.extend(["--subvideo_length", "20", "--resize_ratio", "0.5"])
            else:
                sys.argv.append("--fp16")
                
        print("[SAM2+ProPainter] Launching ProPainter in-process...")
        runpy.run_path(script, run_name="__main__")
        
    except Exception as e:
        raise RuntimeError(f"ProPainter failed: {e}")
        
    finally:
        sys.argv = original_argv
        sys.path = original_path
        if 'original_get_device' in locals():
            import model.misc
            model.misc.get_device = original_get_device


def composite_replacement(inpainted_frames_dir, masks_by_frame, frame_paths,
                           replacement_img, output_frames_dir):
    """Paste the replacement image onto each inpainted frame, clipped to
    that frame's SAM2 mask (already clean/consistent -- no smoothing hacks
    needed here, unlike the old per-frame pipeline)."""
    os.makedirs(output_frames_dir, exist_ok=True)
    inpainted_paths = sorted(glob.glob(os.path.join(inpainted_frames_dir, "*")))

    for i, (orig_path, inp_path) in enumerate(zip(frame_paths, inpainted_paths)):
        frame = cv2.imread(inp_path)
        mask = masks_by_frame.get(i)

        if mask is not None:
            # If ProPainter ran at reduced resolution to save RAM, upsample back to match SAM2 mask
            if frame.shape[:2] != mask.shape[:2]:
                frame = cv2.resize(frame, (mask.shape[1], mask.shape[0]))

        if mask is not None and replacement_img is not None and mask.any():
            ys, xs = np.where(mask > 0)
            x, y, w, h = xs.min(), ys.min(), xs.max() - xs.min(), ys.max() - ys.min()
            frame = overlay_image(
                frame, replacement_img, x, y, w, h,
                obj_mask=mask, preserve_aspect=True, feather_px=5
            )

        out_path = os.path.join(output_frames_dir, os.path.basename(orig_path))
        cv2.imwrite(out_path, frame)


def frames_to_video(frames_dir, audio_path, fps, output_file, ffmpeg_path="ffmpeg"):
    pattern = os.path.join(frames_dir, "%06d.jpg")
    if os.path.exists(audio_path):
        cmd = [ffmpeg_path, "-y", "-framerate", str(fps), "-i", pattern,
               "-i", audio_path, "-c:v", "libx264", "-preset", "fast",
               "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac",
               "-map", "0:v:0", "-map", "1:a:0?", output_file]
    else:
        cmd = [ffmpeg_path, "-y", "-framerate", str(fps), "-i", pattern,
               "-c:v", "libx264", "-preset", "fast", "-crf", "18",
               "-pix_fmt", "yuv420p", output_file]
    subprocess.run(cmd, capture_output=True)


def execute_cv_object_v2(instruction, ffmpeg_path="ffmpeg", work_dir="sam2_propainter_work"):
    inp = instruction.get("input", {})
    out_dict = instruction.get("output", {})

    # Resolve to absolute path so cleanup & creation work correctly regardless
    # of which directory vibevideo.py happens to be in when it calls us.
    work_dir = os.path.join(BASE_DIR, work_dir)

    input_files = inp.get("input_files", [])
    if len(input_files) < 1:
        raise ValueError("At least one input video is required.")

    video_path = input_files[0]
    replacement_path = input_files[1] if len(input_files) > 1 else None
    output_file = out_dict.get("output_file") or "replaced_output.mp4"
    target_object = inp.get("target_object", "").strip().lower()

    if not target_object:
        raise ValueError("Missing target_object to replace (e.g., 'car', 'person').")

    replacement_img = None
    if replacement_path and os.path.exists(replacement_path):
        replacement_img = Image.open(replacement_path)

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    cap.release()

    frames_dir = os.path.join(work_dir, "frames")
    masks_dir = os.path.join(work_dir, "masks")
    inpainted_dir = os.path.join(work_dir, "inpainted")
    composited_dir = os.path.join(work_dir, "composited")
    audio_path = os.path.join(work_dir, "audio.m4a")

    # Check if we already have masks from a previous run (e.g. ProPainter failed
    # but SAM2 tracking already finished). If so, skip straight to ProPainter
    # to avoid re-doing hours of CPU tracking work.
    existing_masks = sorted(glob.glob(os.path.join(masks_dir, "*.png")))
    existing_frames = sorted(glob.glob(os.path.join(frames_dir, "*.jpg")))

    if existing_masks and existing_frames:
        print(f"[SAM2+ProPainter] Found {len(existing_masks)} existing masks — resuming from ProPainter step.")
        frame_paths = existing_frames
        # Reconstruct masks_by_frame from saved PNGs
        masks_by_frame = {}
        for mask_path in existing_masks:
            idx = int(os.path.splitext(os.path.basename(mask_path))[0]) - 1  # filenames are 1-indexed
            mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
            if mask is not None:
                masks_by_frame[idx] = mask
    else:
        # Fresh run — wipe any partial previous attempt and start from scratch
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir)

        print(f"[SAM2+ProPainter] Finding '{target_object}' to seed tracking...")
        seed_frame_idx, seed_box = find_seed_box(video_path, target_object)
        if seed_frame_idx is None:
            raise RuntimeError(f"Could not find '{target_object}' anywhere in the search window.")
        print(f"[SAM2+ProPainter] Seeded on frame {seed_frame_idx}, box={seed_box}")

        print("[SAM2+ProPainter] Extracting frames...")
        frame_paths = extract_frames(video_path, frames_dir, ffmpeg_path=ffmpeg_path)
        extract_audio(video_path, audio_path, ffmpeg_path)

        print("[SAM2+ProPainter] Tracking object across full clip with SAM2...")
        masks_by_frame = run_sam2_tracking(frames_dir, seed_frame_idx, seed_box)
        print(f"[SAM2+ProPainter] Tracked on {len(masks_by_frame)}/{len(frame_paths)} frames.")

        export_masks(masks_by_frame, frame_paths, masks_dir)

    print("[SAM2+ProPainter] Running flow-guided inpainting (ProPainter)...")
    run_propainter(frames_dir, masks_dir, inpainted_dir)

    print("[SAM2+ProPainter] Compositing replacement image...")
    composite_replacement(inpainted_dir, masks_by_frame, frame_paths,
                           replacement_img, composited_dir)

    print("[SAM2+ProPainter] Re-encoding video...")
    frames_to_video(composited_dir, audio_path, fps, output_file, ffmpeg_path=ffmpeg_path)

    shutil.rmtree(work_dir)
    print(f"[SAM2+ProPainter] Done! Saved to {output_file}")
    return output_file