import os
import subprocess
import imageio_ffmpeg

def execute_insightface(implementation, instruction):
    if implementation != "face_swap_video":
        raise ValueError(f"Unknown insightface implementation: {implementation}")
        
    import cv2
    import numpy as np
    import insightface
    from insightface.app import FaceAnalysis

    inp = instruction["input"]
    input_files = inp.get("input_files", [])
    output_file = instruction["output"].get("output_file")
    
    if len(input_files) < 2:
        raise ValueError("face_swap_video requires 1 video file and 1 image file.")

    video_path, photo_path = None, None
    for f in input_files:
        ext = os.path.splitext(f.lower())[1]
        if ext in [".mp4", ".mkv", ".avi", ".mov", ".webm"]:
            video_path = f
        elif ext in [".jpg", ".jpeg", ".png"]:
            photo_path = f
            
    if not video_path or not photo_path:
        video_path = input_files[0]
        photo_path = input_files[1]
        
    if not output_file:
        base, ext = os.path.splitext(video_path)
        output_file = f"{base}_faceswap{ext}"

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file '{video_path}' does not exist.")
    if not os.path.exists(photo_path):
        raise FileNotFoundError(f"Photo file '{photo_path}' does not exist.")
        
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    model_path = os.path.join(BASE_DIR, "models/inswapper_128.onnx")
    if not os.path.exists(model_path):
        print("Downloading inswapper_128.onnx model (~500MB) to models/. This might take a few minutes...")
        import urllib.request
        try:
            url = "https://huggingface.co/ezioruan/inswapper_128.onnx/resolve/main/inswapper_128.onnx"
            os.makedirs(os.path.join(BASE_DIR, "models"), exist_ok=True)
            urllib.request.urlretrieve(url, model_path)
            print("Model downloaded.")
        except Exception as e:
            raise RuntimeError(f"Error downloading model: {e}")
            
    print("Loading InsightFace models...")
    app = FaceAnalysis(name='buffalo_l')
    app.prepare(ctx_id=0, det_size=(640, 640))
    swapper = insightface.model_zoo.get_model(model_path)
    
    source_img = cv2.imread(photo_path)
    source_faces = app.get(source_img)
    if not source_faces:
        raise ValueError("Could not detect any face in the source photo.")
    source_face = source_faces[0]
    
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    temp_output = "temp_swap.mp4"
    out = cv2.VideoWriter(temp_output, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
    
    print(f"Processing video frames... (Total frames: {total_frames})")
    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        faces_in_frame = app.get(frame)
        if faces_in_frame:
            target_face = faces_in_frame[0]
            try:
                frame = swapper.get(frame, target_face, source_face, paste_back=True)
            except Exception:
                pass
                
        out.write(frame)
        frame_count += 1
        if frame_count % 30 == 0:
            print(f"Processed {frame_count}/{total_frames} frames...")
            
    cap.release()
    out.release()
    
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    print("Post-processing video with FFmpeg to preserve audio and ensure compatibility...")
    cmd = f'"{ffmpeg_path}" -y -i "{temp_output}" -i "{video_path}" -c:v libx264 -pix_fmt yuv420p -map 0:v -map 1:a? -c:a aac -shortest "{output_file}"'
    subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    if os.path.exists(temp_output):
        os.remove(temp_output)
        
    print(f"Face swap complete. Saved video as '{output_file}'")
    return output_file
