from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import re
import subprocess
import os
import imageio_ffmpeg
from audacity_engine import AudacityEngine

# path to ffmpeg binary
ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()

def scan_media_files():
    """Scan current directory for media files and build working name mappings."""
    extensions = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".mp3", ".wav", ".png", ".jpg", ".jpeg"}
    files = [f for f in os.listdir('.') if os.path.isfile(f) and os.path.splitext(f.lower())[1] in extensions]
    files.sort(key=lambda x: x.lower())
    
    mapping = {}
    for idx, filename in enumerate(files, start=1):
        mapping[f"file{idx}"] = filename
        mapping[f"f{idx}"] = filename
        mapping[f"[{idx}]"] = filename
    return files, mapping

def preprocess_query(query, mapping):
    """Replace working names like file1, f1, [1] or file 1 with actual file names."""
    # Normalize "file 1" -> "file1"
    query = re.sub(r'\bfile\s+(\d+)\b', r'file\1', query, flags=re.I)
    
    # Replace keys from longest to shortest
    def replace_func(match):
        word = match.group(0).lower()
        return mapping.get(word, match.group(0))
        
    # Match pattern: f\d+ or file\d+ but not followed by dot and extension
    query = re.sub(r'\b(file\d+|f\d+)\b(?!\s*\.(?:mp4|mkv|avi|mov|webm|mp3|wav|png|jpg|jpeg))', replace_func, query, flags=re.I)
    
    # Match pattern: \[\d+\] but not followed by dot and extension
    def replace_bracket(match):
        bracketed = match.group(0)
        return mapping.get(bracketed, match.group(0))
        
    query = re.sub(r'\[\d+\](?!\s*\.(?:mp4|mkv|avi|mov|webm|mp3|wav|png|jpg|jpeg))', replace_bracket, query)
    
    return query

# training data for intent classification


training_phrases = [
    ("screen_record", "record my screen"),
    ("screen_record", "capture my desktop"),
    ("screen_record", "start screen recording"),
    ("screen_record", "record monitor"),

    ("screen_record_audio", "record screen with audio"),
    ("screen_record_audio", "record screen with microphone"),
    ("screen_record_audio", "capture desktop and sound"),
    ("screen_record_audio", "record display with sound"),

    ("screenshot", "take a screenshot"),
    ("screenshot", "capture screenshot"),
    ("screenshot", "save image of screen"),
    ("screenshot", "grab screen image"),
    ("screenshot", "take a photo of my desktop"),
    ("screenshot", "take a picture of my screen"),
    ("screenshot", "capture a still image"),
    ("screenshot", "save a snapshot of my display"),
    ("screenshot", "grab one frame from the screen"),
    ("screenshot", "take screen photo"),
    ("screenshot", "capture image from monitor"),

    ("video_clip", "clip a video"),
    ("video_clip", "trim my video file"),
    ("video_clip", "cut video from 10 to 20 seconds"),
    ("video_clip", "extract clip from input.mp4"),
    ("video_clip", "trim input.mp4 to output.mp4"),
    ("video_clip", "crop video duration"),
    ("video_clip", "slice video starting from 5 seconds for 15 seconds"),
    ("video_clip", "cut video from start to 30 seconds"),

    ("video_merge", "merge videos together"),
    ("video_merge", "combine two videos"),
    ("video_merge", "join video1.mp4 and video2.mp4"),
    ("video_merge", "concatenate videos into output.mp4"),
    ("video_merge", "merge vid1.mp4 and vid2.mp4 with fade transition"),
    ("video_merge", "combine vid1.mp4 and vid2.mp4 into final.mp4"),
    ("video_merge", "join videos using slideleft"),

    ("audio_trim", "trim audio from 10 to 30 seconds"),
    ("audio_trim", "cut audio song.mp3 from 00:00:10 to 00:00:30"),
    ("audio_trim", "clip audio file"),

    ("audio_volume", "increase volume of song.mp3"),
    ("audio_volume", "make audio volume 2.0"),
    ("audio_volume", "make audio quieter by half"),
    ("audio_volume", "adjust volume to 0.5"),

    ("audio_fade", "apply fade in of 3 seconds to sound.mp3"),
    ("audio_fade", "fade out audio track"),
    ("audio_fade", "fade in starting from 0 for 5 seconds"),

    ("audio_mix", "mix voice.mp3 and music.mp3"),
    ("audio_mix", "combine audio tracks voice and music"),
    ("audio_mix", "mix two audio files together"),

    ("audio_speed", "speed up sound to 1.5x"),
    ("audio_speed", "slow down audio 0.8x"),
    ("audio_speed", "change audio tempo to 1.2"),

    ("audio_reverse", "reverse audio track"),
    ("audio_reverse", "play song.mp3 backwards"),
    ("audio_reverse", "reverse sound file"),

    ("audio_extract", "extract audio from video.mp4 to output.mp3"),
    ("audio_extract", "rip audio track from clip.mp4"),
    ("audio_extract", "convert video to mp3"),

    ("audio_replace", "replace audio in video.mp4 with backing.mp3"),
    ("audio_replace", "add background music to video"),
    ("audio_replace", "combine video and audio track"),

    ("audio_visual", "generate waveform video for song.mp3"),
    ("audio_visual", "generate spectrogram image of audio"),
    ("audio_visual", "create audio visualizer waveform"),

    ("face_swap_video", "swap face in video with photo"),
    ("face_swap_video", "replace face in video.mp4 with face.jpg"),
    ("face_swap_video", "put my face in video"),
    ("face_swap_video", "face replace video with photo"),
]

# load model and build faiss index

print("Loading embedding model...")

model = SentenceTransformer('all-MiniLM-L6-v2')

phrases = [x[1] for x in training_phrases]
intents = [x[0] for x in training_phrases]

embeddings = model.encode(phrases)

dimension = embeddings.shape[1]

index = faiss.IndexFlatL2(dimension)
index.add(np.array(embeddings).astype("float32"))

print("FAISS index ready.\n")

# extract parameters from query

def parse_parameters(text):

    params = {
        "fps": 30,
        "duration": None,
        "filename": None,
        "input_files": [],
        "output_file": None,
        "start_time": None,
        "end_time": None,
        "transition": None,
        "speed_multiplier": 1.0,
        "volume_level": 1.0,
        "visual_type": "waveform",
        "fade_type": "in",
        "fade_duration": 3.0
    }

    # fps

    m = re.search(r'(\d+)\s*fps', text, re.I)
    if m:
        params["fps"] = int(m.group(1))

    # extract all potential files
    all_files = re.findall(r'\b([A-Za-z0-9_-]+\.(?:mp4|mkv|avi|mov|webm|mp3|wav|png|jpg|jpeg))\b', text, re.I)

    # check if merging
    is_merge = any(w in text.lower() for w in ["merge", "combine", "join", "concatenate", "concat"])

    # find output file (as/into/output)
    m_out = re.search(r'\b(?:as|into|output)\s+([A-Za-z0-9_-]+\.(?:mp4|mkv|avi|mov|webm|mp3|wav|png|jpg|jpeg))\b', text, re.I)
    if m_out:
        params["output_file"] = m_out.group(1)
        params["input_files"] = [f for f in all_files if f.lower() != params["output_file"].lower()]
    elif is_merge:
        params["input_files"] = all_files
        params["output_file"] = "merged.mp4"
    else:
        if all_files:
            if len(all_files) == 1:
                params["input_files"] = [all_files[0]]
            elif len(all_files) >= 2:
                params["output_file"] = all_files[-1]
                params["input_files"] = all_files[:-1]

    # legacy compatibility fallback
    if params["output_file"]:
        params["filename"] = params["output_file"]
    elif all_files:
        params["filename"] = all_files[-1]

    # start time
    m_start = re.search(r'\b(?:from|start|starting|ss|at)\s+(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?|\d{1,2}:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?)(?!\s*fps)\b', text, re.I)
    if m_start:
        params["start_time"] = m_start.group(1)

    # end time
    m_end = re.search(r'\b(?:to|end|ending)\s+(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?|\d{1,2}:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?)(?!\s*(?:fps|x|X|\.?\d|[A-Za-z0-9_-]+\.))\b', text, re.I)
    if m_end:
        params["end_time"] = m_end.group(1)

    # duration limit
    m_dur = re.search(r'\b(?:duration|for|t)\s+(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?|\d{1,2}:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?:sec|second|min|minute|hour)?\b', text, re.I)
    if m_dur:
        params["duration"] = m_dur.group(1)

    # transition style
    m_trans = re.search(r'\b(?:transition|using)\s+([a-zA-Z]+)(?!\.[a-zA-Z0-9]+)\b', text, re.I)
    if m_trans:
        params["transition"] = m_trans.group(1).lower()
    else:
        transitions = ["fade", "fadeblack", "fadewhite", "slideleft", "slideright", "slideup", "slidedown",
                       "wipeleft", "wiperight", "wipeup", "wipedown", "circleopen", "circleclose", "pixelize", "dissolve"]
        for t in transitions:
            if re.search(r'\b' + t + r'\b', text, re.I):
                params["transition"] = t
                break

    # speed_multiplier
    m_speed = re.search(r'\b(?:speed|tempo)\s*(?:up|down|to)?\s*(\d+(?:\.\d+)?)(?:x)?\b', text, re.I)
    if m_speed:
        params["speed_multiplier"] = float(m_speed.group(1))
    elif "speed up" in text.lower():
        params["speed_multiplier"] = 1.5
    elif "slow down" in text.lower():
        params["speed_multiplier"] = 0.8
        
    # volume_level
    m_vol = re.search(r'\bvolume\s*(?:to|of)?\s*(\d+(?:\.\d+)?)\b', text, re.I)
    if m_vol:
        params["volume_level"] = float(m_vol.group(1))
    elif "double volume" in text.lower():
        params["volume_level"] = 2.0
    elif "half volume" in text.lower():
        params["volume_level"] = 0.5
        
    # visual_type
    if "spectrogram" in text.lower():
        params["visual_type"] = "spectrogram"
    else:
        params["visual_type"] = "waveform"
        
    # fade_type
    if "fade out" in text.lower() or "fade-out" in text.lower():
        params["fade_type"] = "out"
    else:
        params["fade_type"] = "in"
        
    # fade_duration
    m_fade = re.search(r'\bfade\s*(?:in|out)?\s*(?:of|for|duration)?\s*(\d+(?:\.\d+)?)\s*(?:sec|second)?\b', text, re.I)
    if m_fade:
        params["fade_duration"] = float(m_fade.group(1))

    return params


# --- Tool implementations ---

def take_screenshot(params):
    filename = params["filename"] or "screenshot.png"

    cmd = (
        f'"{ffmpeg_path}" '
        f"-f gdigrab "
        f"-i desktop "
        f"-vframes 1 "
        f"{filename}"
    )

    print(cmd)

    subprocess.run(cmd, shell=True)

def record_screen(params):

    fps = params["fps"]

    filename = params["filename"] or "recording.mp4"

    cmd = (
        f'"{ffmpeg_path}" '
        f"-framerate {fps} "
        f"-f gdigrab "
        f"-i desktop "
        f"{filename}"
    )

    print(cmd)

    subprocess.run(cmd, shell=True)

def record_screen_audio(params):

    fps = params["fps"]

    filename = params["filename"] or "recording_audio.mp4"

    cmd = (
        f'"{ffmpeg_path}" '
        f"-framerate {fps} "
        f"-f gdigrab "
        f"-i desktop "
        f"{filename}"
    )

    print(cmd)

    subprocess.run(cmd, shell=True)


def get_video_duration(filepath):
    """Gets the duration of a video file using ffprobe or ffmpeg fallback."""
    if not os.path.exists(filepath):
        print(f"Error: File '{filepath}' does not exist.")
        return None
        
    ffprobe_path = ffmpeg_path.replace("ffmpeg.exe", "ffprobe.exe").replace("ffmpeg", "ffprobe")
    if os.path.exists(ffprobe_path):
        cmd = f'"{ffprobe_path}" -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{filepath}"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        try:
            return float(result.stdout.strip())
        except ValueError:
            pass

    # Fallback to ffmpeg -i
    cmd = f'"{ffmpeg_path}" -i "{filepath}"'
    result = subprocess.run(cmd, shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    match = re.search(r'Duration:\s*(\d{2}):(\d{2}):(\d{2})\.(\d{2})', result.stderr)
    if match:
        hours, mins, secs, ms = map(int, match.groups())
        return hours * 3600 + mins * 60 + secs + ms / 100.0
    return None

def has_audio_stream(filepath):
    """Detects if the video file contains an audio stream."""
    if not os.path.exists(filepath):
        return False
    cmd = f'"{ffmpeg_path}" -i "{filepath}"'
    result = subprocess.run(cmd, shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    return "Audio:" in result.stderr

def clip_video(params):
    input_files = params.get("input_files", [])
    output_file = params.get("output_file")
    start_time = params.get("start_time")
    end_time = params.get("end_time")
    duration = params.get("duration")

    if not input_files:
        print("Error: No input file specified for clipping.")
        return
    
    input_file = input_files[0]
    if not os.path.exists(input_file):
        print(f"Error: Input file '{input_file}' does not exist.")
        return

    if not output_file:
        base, ext = os.path.splitext(input_file)
        output_file = f"{base}_clipped{ext}"

    seek_opts = []
    if start_time is not None:
        seek_opts.extend(["-ss", str(start_time)])
    
    seek_opts.extend(["-i", f'"{input_file}"'])
    
    if end_time is not None:
        seek_opts.extend(["-to", str(end_time)])
    elif duration is not None:
        seek_opts.extend(["-t", str(duration)])

    cmd_parts = [f'"{ffmpeg_path}"', "-y"] + seek_opts + ["-c:v", "libx264", "-c:a", "aac", f'"{output_file}"']
    cmd = " ".join(cmd_parts)
    print(f"Executing: {cmd}")
    subprocess.run(cmd, shell=True)
    print(f"Clipped video saved as '{output_file}'")

def merge_videos(params):
    input_files = params.get("input_files", [])
    output_file = params.get("output_file") or "merged.mp4"
    transition = params.get("transition")

    if len(input_files) < 2:
        print("Error: Merge requires at least 2 input files.")
        return

    for f in input_files:
        if not os.path.exists(f):
            print(f"Error: Input file '{f}' does not exist.")
            return

    if transition and len(input_files) == 2:
        v1, v2 = input_files[0], input_files[1]
        d1 = get_video_duration(v1)
        if d1 is not None:
            t_dur = 1.0
            if d1 <= t_dur:
                t_dur = d1 / 2.0
            offset = d1 - t_dur

            audio1 = has_audio_stream(v1)
            audio2 = has_audio_stream(v2)

            print(f"Applying '{transition}' transition between '{v1}' (duration: {d1:.2f}s) and '{v2}' at offset {offset:.2f}s.")
            
            filter_parts = [
                f"[0:v]scale=1280:720,fps=30,settb=AVTB[v0]",
                f"[1:v]scale=1280:720,fps=30,settb=AVTB[v1]",
                f"[v0][v1]xfade=transition={transition}:duration={t_dur}:offset={offset}[v]"
            ]
            
            map_opts = ['-map "[v]"']
            
            if audio1 and audio2:
                filter_parts.append(f"[0:a][1:a]acrossfade=d={t_dur}[a]")
                map_opts.append('-map "[a]"')
            elif audio1:
                map_opts.append('-map 0:a')
            elif audio2:
                map_opts.append('-map 1:a')

            filter_str = ";".join(filter_parts)
            cmd = f'"{ffmpeg_path}" -y -i "{v1}" -i "{v2}" -filter_complex "{filter_str}" {" ".join(map_opts)} -c:v libx264 -pix_fmt yuv420p -c:a aac "{output_file}"'
            print(f"Executing: {cmd}")
            subprocess.run(cmd, shell=True)
            print(f"Merged video with transition saved as '{output_file}'")
            return
        else:
            print("Warning: Could not determine first video's duration. Falling back to simple concatenation.")

    concat_list_file = "concat_list.txt"
    try:
        with open(concat_list_file, "w") as f_list:
            for f in input_files:
                abs_path = os.path.abspath(f).replace("\\", "/")
                f_list.write(f"file '{abs_path}'\n")
        
        cmd = f'"{ffmpeg_path}" -y -f concat -safe 0 -i {concat_list_file} -c copy "{output_file}"'
        print(f"Executing: {cmd}")
        subprocess.run(cmd, shell=True)
        print(f"Merged video saved as '{output_file}'")
    finally:
        if os.path.exists(concat_list_file):
            os.remove(concat_list_file)

def resolve_shortcut(path):
    if not path:
        return path
    path = path.strip()
    path_clean = re.sub(r'[\[\]\s]', '', path).lower()
    m = re.match(r'^(?:file|f)?(\d+)$', path_clean)
    if m:
        idx = int(m.group(1))
        extensions = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".mp3", ".wav", ".png", ".jpg", ".jpeg"}
        files = [f for f in os.listdir('.') if os.path.isfile(f) and os.path.splitext(f.lower())[1] in extensions]
        files.sort(key=lambda x: x.lower())
        if 1 <= idx <= len(files):
            return files[idx - 1]
    return path

def audio_trim(params):
    input_files = params.get("input_files", [])
    output_file = params.get("output_file")
    start_time = params.get("start_time") or "0"
    end_time = params.get("end_time")
    duration = params.get("duration")

    if not input_files:
        print("Error: No input audio file specified.")
        return
    a1 = input_files[0]
    if not os.path.exists(a1):
        print(f"Error: Input file '{a1}' does not exist.")
        return
    if not output_file:
        base, ext = os.path.splitext(a1)
        output_file = f"{base}_trimmed{ext}"

    seek_opts = [f'-ss {start_time}']
    if end_time is not None:
        seek_opts.append(f'-to {end_time}')
    elif duration is not None:
        seek_opts.append(f'-t {duration}')

    cmd = f'"{ffmpeg_path}" -y -i "{a1}" {" ".join(seek_opts)} -c copy "{output_file}"'
    print(f"Executing: {cmd}")
    subprocess.run(cmd, shell=True)
    print(f"Trimmed audio saved as '{output_file}'")

def audio_volume(params):
    input_files = params.get("input_files", [])
    output_file = params.get("output_file")
    volume = params.get("volume_level", 1.0)

    if not input_files:
        print("Error: No input audio file specified.")
        return
    a1 = input_files[0]
    if not os.path.exists(a1):
        print(f"Error: Input file '{a1}' does not exist.")
        return
    if not output_file:
        base, ext = os.path.splitext(a1)
        output_file = f"{base}_volume{ext}"

    cmd = f'"{ffmpeg_path}" -y -i "{a1}" -filter:a "volume={volume}" "{output_file}"'
    print(f"Executing: {cmd}")
    subprocess.run(cmd, shell=True)
    print(f"Adjusted volume video/audio saved as '{output_file}'")

def audio_fade(params):
    input_files = params.get("input_files", [])
    output_file = params.get("output_file")
    fade_type = params.get("fade_type", "in")
    fade_duration = params.get("fade_duration", 3.0)
    start_time = params.get("start_time") or "0"

    if not input_files:
        print("Error: No input audio file specified.")
        return
    a1 = input_files[0]
    if not os.path.exists(a1):
        print(f"Error: Input file '{a1}' does not exist.")
        return
    if not output_file:
        base, ext = os.path.splitext(a1)
        output_file = f"{base}_fade_{fade_type}{ext}"

    st_val = 0
    if fade_type == "out":
        duration_total = get_video_duration(a1)
        if duration_total is not None:
            st_val = max(0.0, duration_total - fade_duration)
        else:
            print("Warning: Could not determine audio duration for fade out. Fading out at start.")
            st_val = 0.0
    else:
        try:
            st_val = float(start_time)
        except ValueError:
            st_val = 0.0

    af_filter = f"afade=t={fade_type}:st={st_val}:d={fade_duration}"
    cmd = f'"{ffmpeg_path}" -y -i "{a1}" -af "{af_filter}" "{output_file}"'
    print(f"Executing: {cmd}")
    subprocess.run(cmd, shell=True)
    print(f"Faded audio saved as '{output_file}'")

def audio_mix(params):
    input_files = params.get("input_files", [])
    output_file = params.get("output_file") or "mixed.mp3"

    if len(input_files) < 2:
        print("Error: Mixing requires at least 2 input files.")
        return
    for f in input_files:
        if not os.path.exists(f):
            print(f"Error: Input file '{f}' does not exist.")
            return

    inputs_str = " ".join([f'-i "{f}"' for f in input_files])
    cmd = f'"{ffmpeg_path}" -y {inputs_str} -filter_complex amix=inputs={len(input_files)} "{output_file}"'
    print(f"Executing: {cmd}")
    subprocess.run(cmd, shell=True)
    print(f"Mixed audio saved as '{output_file}'")

def audio_speed(params):
    input_files = params.get("input_files", [])
    output_file = params.get("output_file")
    speed = params.get("speed_multiplier", 1.0)

    if not input_files:
        print("Error: No input audio file specified.")
        return
    a1 = input_files[0]
    if not os.path.exists(a1):
        print(f"Error: Input file '{a1}' does not exist.")
        return
    if not output_file:
        base, ext = os.path.splitext(a1)
        output_file = f"{base}_speed{ext}"

    cmd = f'"{ffmpeg_path}" -y -i "{a1}" -filter:a "atempo={speed}" "{output_file}"'
    print(f"Executing: {cmd}")
    subprocess.run(cmd, shell=True)
    print(f"Speed altered audio saved as '{output_file}'")

def audio_reverse(params):
    input_files = params.get("input_files", [])
    output_file = params.get("output_file")

    if not input_files:
        print("Error: No input audio file specified.")
        return
    a1 = input_files[0]
    if not os.path.exists(a1):
        print(f"Error: Input file '{a1}' does not exist.")
        return
    if not output_file:
        base, ext = os.path.splitext(a1)
        output_file = f"{base}_reversed{ext}"

    cmd = f'"{ffmpeg_path}" -y -i "{a1}" -filter:a areverse "{output_file}"'
    print(f"Executing: {cmd}")
    subprocess.run(cmd, shell=True)
    print(f"Reversed audio saved as '{output_file}'")

def audio_extract(params):
    input_files = params.get("input_files", [])
    output_file = params.get("output_file")

    if not input_files:
        print("Error: No input video file specified.")
        return
    v1 = input_files[0]
    if not os.path.exists(v1):
        print(f"Error: Input file '{v1}' does not exist.")
        return
    if not output_file:
        base, _ = os.path.splitext(v1)
        output_file = f"{base}_extracted.mp3"

    cmd = f'"{ffmpeg_path}" -y -i "{v1}" -vn -c:a libmp3lame "{output_file}"'
    print(f"Executing: {cmd}")
    subprocess.run(cmd, shell=True)
    print(f"Extracted audio saved as '{output_file}'")

def audio_replace(params):
    input_files = params.get("input_files", [])
    output_file = params.get("output_file") or "replaced_output.mp4"

    if len(input_files) < 2:
        print("Error: Replace audio requires 1 video file and 1 audio file.")
        return
    
    v_file, a_file = None, None
    for f in input_files:
        _, ext = os.path.splitext(f.lower())
        if ext in [".mp3", ".wav"]:
            a_file = f
        elif ext in [".mp4", ".mkv", ".avi", ".mov", ".webm"]:
            v_file = f
    
    if not v_file or not a_file:
        v_file, a_file = input_files[0], input_files[1]

    if not os.path.exists(v_file) or not os.path.exists(a_file):
        print("Error: Input files do not exist.")
        return

    cmd = f'"{ffmpeg_path}" -y -i "{v_file}" -i "{a_file}" -map 0:v -map 1:a -c:v copy -shortest "{output_file}"'
    print(f"Executing: {cmd}")
    subprocess.run(cmd, shell=True)
    print(f"Replaced audio output saved as '{output_file}'")

def audio_visual(params):
    input_files = params.get("input_files", [])
    output_file = params.get("output_file")
    visual_type = params.get("visual_type", "waveform")

    if not input_files:
        print("Error: No input audio file specified.")
        return
    a1 = input_files[0]
    if not os.path.exists(a1):
        print(f"Error: Input file '{a1}' does not exist.")
        return
    
    if not output_file:
        if visual_type == "waveform":
            output_file = "waveform.mp4"
        else:
            output_file = "spectrogram.png"

    if visual_type == "waveform":
        cmd = f'"{ffmpeg_path}" -y -i "{a1}" -filter_complex "[0:a]showwaves=s=1280x720:mode=line[v]" -map "[v]" -c:v libx264 "{output_file}"'
    else:
        cmd = f'"{ffmpeg_path}" -y -i "{a1}" -lavfi showspectrumpic=s=1280x720 "{output_file}"'

    print(f"Executing: {cmd}")
    subprocess.run(cmd, shell=True)
    print(f"Visual representation saved as '{output_file}'")

def face_swap_video(params):
    import cv2
    import numpy as np
    import insightface
    from insightface.app import FaceAnalysis
    import urllib.request

    input_files = params.get("input_files", [])
    output_file = params.get("output_file")
    
    # Workaround for parse_parameters incorrectly assigning the second input as output_file
    if len(input_files) == 1 and output_file:
        input_files.append(output_file)
        output_file = None
        
    if len(input_files) < 2:
        print("Error: face_swap_video requires 1 video file and 1 image file.")
        return

    # Try to distinguish video and image
    video_path, photo_path = None, None
    for f in input_files:
        ext = os.path.splitext(f.lower())[1]
        if ext in [".mp4", ".mkv", ".avi", ".mov", ".webm"]:
            video_path = resolve_shortcut(f)
        elif ext in [".jpg", ".jpeg", ".png"]:
            photo_path = resolve_shortcut(f)
    
    # Fallback if both have same extension (unlikely for video/photo but possible)
    if not video_path or not photo_path:
        video_path = resolve_shortcut(input_files[0])
        photo_path = resolve_shortcut(input_files[1])
        
    if not output_file:
        base, ext = os.path.splitext(video_path)
        output_file = f"{base}_faceswap{ext}"
        
    if not os.path.exists(video_path):
        print(f"Error: Video file '{video_path}' does not exist.")
        return
    if not os.path.exists(photo_path):
        print(f"Error: Photo file '{photo_path}' does not exist.")
        return
        
    model_path = "inswapper_128.onnx"
    if not os.path.exists(model_path):
        print("Downloading inswapper_128.onnx model (~500MB). This might take a few minutes...")
        try:
            url = "https://huggingface.co/ezioruan/inswapper_128.onnx/resolve/main/inswapper_128.onnx"
            urllib.request.urlretrieve(url, model_path)
            print("Model downloaded.")
        except Exception as e:
            print(f"Error downloading model: {e}")
            return
            
    print("Loading InsightFace models...")
    app = FaceAnalysis(name='buffalo_l')
    app.prepare(ctx_id=0, det_size=(640, 640))
    swapper = insightface.model_zoo.get_model(model_path)
    
    source_img = cv2.imread(photo_path)
    source_faces = app.get(source_img)
    if not source_faces:
        print("Error: Could not detect any face in the source photo.")
        return
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
            # Swap the largest face found or first face
            target_face = faces_in_frame[0]
            try:
                frame = swapper.get(frame, target_face, source_face, paste_back=True)
            except Exception as e:
                pass # ignore swap error on a specific frame
                
        out.write(frame)
        frame_count += 1
        if frame_count % 30 == 0:
            print(f"Processed {frame_count}/{total_frames} frames...")
            
    cap.release()
    out.release()
    
    print("Post-processing video with FFmpeg to preserve audio and ensure compatibility...")
    cmd = f'"{ffmpeg_path}" -y -i "{temp_output}" -i "{video_path}" -c:v libx264 -pix_fmt yuv420p -map 0:v -map 1:a? -c:a aac -shortest "{output_file}"'
    subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    if os.path.exists(temp_output):
        os.remove(temp_output)
        
    print(f"Face swap complete. Saved video as '{output_file}'")

def execute_tool(intent, params):

    tool = TOOLS.get(intent)

    if not tool:
        print("Unknown tool")
        return

    tool(params)

TOOLS = {
    "screenshot": take_screenshot,
    "screen_record": record_screen,
    "screen_record_audio": record_screen_audio,
    "video_clip": clip_video,
    "video_merge": merge_videos,
    "audio_trim": audio_trim,
    "audio_volume": audio_volume,
    "audio_fade": audio_fade,
    "audio_mix": audio_mix,
    "audio_speed": audio_speed,
    "audio_reverse": audio_reverse,
    "audio_extract": audio_extract,
    "audio_replace": audio_replace,
    "audio_visual": audio_visual,
    "face_swap_video": face_swap_video,
}




def detect_intent(query):

    query_embedding = model.encode([query])

    distances, indices = index.search(
        np.array(query_embedding).astype("float32"),
        3
    )

    print("\nTop matches:")
    for rank, idx in enumerate(indices[0]):
        print(
            f"{rank+1}. {intents[idx]} | {phrases[idx]} | distance={distances[0][rank]:.2f}"
        )

    best_idx = indices[0][0]
    best_distance = distances[0][0]

    intent = intents[best_idx]

    return intent, best_distance


# --- CLI Prompt Loop ---

if __name__ == "__main__":
    while True:
        media_files, file_mapping = scan_media_files()
        if media_files:
            print("\nAvailable files:")
            for idx, f in enumerate(media_files, start=1):
                print(f"  [{idx}] {f}")
        
        query = input("\nCommand: ")

        if query.lower() in ["quit", "exit"]:
            break

        processed_query = preprocess_query(query, file_mapping)
        if processed_query != query:
            print(f"Translated: {processed_query}")

        intent, distance = detect_intent(processed_query)

        print(f"\nIntent: {intent}")
        print(f"Distance: {distance:.2f}")



        params = parse_parameters(processed_query)

        print("Parameters:", params)

        execute_tool(intent, params)