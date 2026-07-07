import os
import re
import subprocess
import shlex
from pathlib import Path
import imageio_ffmpeg

def get_video_duration(filepath, ffmpeg_path):
    if not os.path.exists(filepath):
        return None
    ffprobe_path = ffmpeg_path.replace("ffmpeg.exe", "ffprobe.exe").replace("ffmpeg", "ffprobe")
    if os.path.exists(ffprobe_path):
        cmd = f'"{ffprobe_path}" -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{filepath}"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        try:
            return float(result.stdout.strip())
        except ValueError:
            pass

    cmd = f'"{ffmpeg_path}" -i "{filepath}"'
    result = subprocess.run(cmd, shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    match = re.search(r'Duration:\s*(\d{2}):(\d{2}):(\d{2})\.(\d{2})', result.stderr)
    if match:
        hours, mins, secs, ms = map(int, match.groups())
        return hours * 3600 + mins * 60 + secs + ms / 100.0
    return None

def has_audio_stream(filepath, ffmpeg_path):
    if not os.path.exists(filepath):
        return False
    cmd = f'"{ffmpeg_path}" -i "{filepath}"'
    result = subprocess.run(cmd, shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    return "Audio:" in result.stderr


FFMPEG_COMMANDS = {
    "extract_audio": '"{ffmpeg_path}" -y -i "{input_file}" -vn -c:a libmp3lame "{output_file}"',
    "take_screenshot": '"{ffmpeg_path}" -y -i "{input_file}" -frames:v 1 "{output_file}"',
    "resize_video": '"{ffmpeg_path}" -y -i "{input_file}" -vf "scale={width}:{height},setsar=1" "{output_file}"'    
}

def get_default_dshow_audio_device(ffmpeg_path):
    cmd = [ffmpeg_path, "-hide_banner", "-f", "dshow", "-list_devices", "true", "-i", "dummy"]
    devices = []
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        for line in result.stderr.splitlines():
            if "(audio)" in line and "dshow" in line:
                parts = line.split('"')
                if len(parts) >= 3:
                    devices.append(parts[1])
    except Exception:
        pass
        
    if not devices:
        return None
        
    # Prioritize Stereo Mix (system audio) if the user has it enabled
    for d in devices:
        if "Stereo Mix" in d:
            return d
            
    # Fallback to built-in Microphone Array over Headset (which might be unplugged and silent)
    for d in devices:
        if "Array" in d:
            return d
            
    return devices[-1] # Fallback to the last one if no array found

def execute_ffmpeg(implementation, instruction):
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    
    inp = instruction.get("input", {})
    input_files = inp.get("input_files", [])
    output_file = instruction.get("output", {}).get("output_file")
    
    # Handle the complex cases first
    if implementation == "screen_record":
        fps = inp.get("fps", 30)
        duration = inp.get("duration")
        output_file = output_file or "recording.mp4"
        dur_opt = f"-t {duration}" if duration else ""
        cmd = f'"{ffmpeg_path}" -y -framerate {fps} -f gdigrab -i desktop {dur_opt} "{output_file}"'
        print(f"\nExecuting: {cmd}")
        subprocess.run(cmd, shell=True)
        return output_file
        
    elif implementation == "screen_record_audio":
        fps = inp.get("fps", 30)
        duration = inp.get("duration")
        output_file = output_file or "recording_audio.mp4"
        dur_opt = f"-t {duration}" if duration else ""
        
        audio_dev = get_default_dshow_audio_device(ffmpeg_path)
        if audio_dev:
            audio_opt = f'{dur_opt} -f dshow -i audio="{audio_dev}" -c:a aac'
        else:
            print("\nWarning: No audio device found, recording video only.")
            audio_opt = ""
            
        cmd = f'"{ffmpeg_path}" -y {dur_opt} -f gdigrab -framerate {fps} -i desktop {audio_opt} -c:v libx264 "{output_file}"'
        print(f"\nExecuting: {cmd}")
        subprocess.run(cmd, shell=True)
        return output_file
        
    elif implementation == "video_clip":
        if not input_files: raise ValueError("No input file specified.")
        input_file = input_files[0]
        if not output_file:
            base, ext = os.path.splitext(input_file)
            output_file = f"{base}_clipped{ext}"
            
        start_time = inp.get("start_time")
        end_time = inp.get("end_time")
        duration = inp.get("duration")
        
        seek_opts = []
        if start_time is not None: seek_opts.extend(["-ss", str(start_time)])
        seek_opts.extend(["-i", f'"{input_file}"'])
        if end_time is not None: seek_opts.extend(["-to", str(end_time)])
        elif duration is not None: seek_opts.extend(["-t", str(duration)])
            
        cmd_parts = [f'"{ffmpeg_path}"', "-y"] + seek_opts + ["-c:v", "libx264", "-c:a", "aac", f'"{output_file}"']
        cmd = " ".join(cmd_parts)
        print(f"\nExecuting: {cmd}")
        subprocess.run(cmd, shell=True)
        return output_file
        
    elif implementation == "video_merge":
        if len(input_files) < 2: raise ValueError("Merge requires at least 2 input files.")
        output_file = output_file or "merged.mp4"
        transition = inp.get("transition")
        
        if transition and len(input_files) == 2:
            v1, v2 = input_files[0], input_files[1]
            d1 = get_video_duration(v1, ffmpeg_path)
            if d1 is not None:
                t_dur = min(1.0, d1 / 2.0)
                offset = d1 - t_dur
                audio1 = has_audio_stream(v1, ffmpeg_path)
                audio2 = has_audio_stream(v2, ffmpeg_path)
                
                filter_parts = [
                    f"[0:v]scale=1280:720,fps=30,settb=AVTB[v0]",
                    f"[1:v]scale=1280:720,fps=30,settb=AVTB[v1]",
                    f"[v0][v1]xfade=transition={transition}:duration={t_dur}:offset={offset}[v]"
                ]
                map_opts = ['-map "[v]"']
                if audio1 and audio2:
                    filter_parts.append(f"[0:a][1:a]acrossfade=d={t_dur}[a]")
                    map_opts.append('-map "[a]"')
                elif audio1: map_opts.append('-map 0:a')
                elif audio2: map_opts.append('-map 1:a')
                    
                filter_str = ";".join(filter_parts)
                cmd = f'"{ffmpeg_path}" -y -i "{v1}" -i "{v2}" -filter_complex "{filter_str}" {" ".join(map_opts)} -c:v libx264 -pix_fmt yuv420p -c:a aac "{output_file}"'
                print(f"\nExecuting: {cmd}")
                subprocess.run(cmd, shell=True)
                return output_file
                
        # Simple concat with audio re‑encoding and timestamp generation
        concat_list_file = "concat_list.txt"
        try:
            with open(concat_list_file, "w") as f_list:
                for f in input_files:
                    f_list.write(f"file '{os.path.abspath(f).replace(os.sep, '/')}'\n")
            # -fflags +genpts forces fresh timestamps; re‑encode audio to a common AAC codec
            cmd = f'"{ffmpeg_path}" -y -fflags +genpts -f concat -safe 0 -i {concat_list_file} -c:v copy -c:a aac -b:a 128k "{output_file}"'
            print(f"\nExecuting: {cmd}")
            subprocess.run(cmd, shell=True)
            return output_file
        finally:
            if os.path.exists(concat_list_file): os.remove(concat_list_file)
            
    elif implementation == "audio_trim":
        if not input_files: raise ValueError("No input file.")
        a1 = input_files[0]
        if not output_file: output_file = f"{os.path.splitext(a1)[0]}_trimmed{os.path.splitext(a1)[1]}"
        start = inp.get("start_time") or "0"
        end = inp.get("end_time")
        duration = inp.get("duration")
        seek_opts = [f"-ss {start}"]
        if end is not None: seek_opts.append(f"-to {end}")
        elif duration is not None: seek_opts.append(f"-t {duration}")
        cmd = f'"{ffmpeg_path}" -y -i "{a1}" {" ".join(seek_opts)} -c copy "{output_file}"'
        print(f"\nExecuting: {cmd}")
        subprocess.run(cmd, shell=True)
        return output_file
        
    elif implementation == "audio_volume":
        if not input_files: raise ValueError("No input file.")
        a1 = input_files[0]
        if not output_file: output_file = f"{os.path.splitext(a1)[0]}_volume{os.path.splitext(a1)[1]}"
        vol = inp.get("volume_level", 1.0)
        cmd = f'"{ffmpeg_path}" -y -i "{a1}" -filter:a "volume={vol}" "{output_file}"'
        print(f"\nExecuting: {cmd}")
        subprocess.run(cmd, shell=True)
        return output_file
        
    elif implementation == "audio_fade":
        if not input_files: raise ValueError("No input file.")
        a1 = input_files[0]
        fade_type = inp.get("fade_type", "in")
        if not output_file: output_file = f"{os.path.splitext(a1)[0]}_fade_{fade_type}{os.path.splitext(a1)[1]}"
        fade_dur = inp.get("fade_duration", 3.0)
        start = inp.get("start_time") or "0"
        st_val = 0.0
        if fade_type == "out":
            dur = get_video_duration(a1, ffmpeg_path)
            if dur: st_val = max(0.0, dur - fade_dur)
        else:
            try: st_val = float(start)
            except ValueError: st_val = 0.0
        af_filter = f"afade=t={fade_type}:st={st_val}:d={fade_dur}"
        cmd = f'"{ffmpeg_path}" -y -i "{a1}" -af "{af_filter}" "{output_file}"'
        print(f"\nExecuting: {cmd}")
        subprocess.run(cmd, shell=True)
        return output_file
        
    elif implementation == "audio_mix":
        if len(input_files) < 2: raise ValueError("Mixing requires at least 2 input files.")
        output_file = output_file or "mixed.mp3"
        inputs_str = " ".join([f'-i "{f}"' for f in input_files])
        cmd = f'"{ffmpeg_path}" -y {inputs_str} -filter_complex amix=inputs={len(input_files)} "{output_file}"'
        print(f"\nExecuting: {cmd}")
        subprocess.run(cmd, shell=True)
        return output_file
        
    elif implementation == "audio_speed":
        if not input_files: raise ValueError("No input file.")
        a1 = input_files[0]
        if not output_file: output_file = f"{os.path.splitext(a1)[0]}_speed{os.path.splitext(a1)[1]}"
        speed = inp.get("speed_multiplier", 1.0)
        cmd = f'"{ffmpeg_path}" -y -i "{a1}" -filter:a "atempo={speed}" "{output_file}"'
        print(f"\nExecuting: {cmd}")
        subprocess.run(cmd, shell=True)
        return output_file
        
    elif implementation == "audio_reverse":
        if not input_files: raise ValueError("No input file.")
        a1 = input_files[0]
        if not output_file: output_file = f"{os.path.splitext(a1)[0]}_reversed{os.path.splitext(a1)[1]}"
        cmd = f'"{ffmpeg_path}" -y -i "{a1}" -filter:a areverse "{output_file}"'
        print(f"\nExecuting: {cmd}")
        subprocess.run(cmd, shell=True)
        return output_file
        
    elif implementation == "audio_replace":
        if len(input_files) < 2: raise ValueError("Requires 1 video and 1 audio file.")
        output_file = output_file or "replaced_output.mp4"
        v_file, a_file = None, None
        for f in input_files:
            if os.path.splitext(f.lower())[1] in [".mp3", ".wav"]: a_file = f
            elif os.path.splitext(f.lower())[1] in [".mp4", ".mkv", ".avi", ".mov", ".webm"]: v_file = f
        if not v_file or not a_file: v_file, a_file = input_files[0], input_files[1]
        cmd = f'"{ffmpeg_path}" -y -i "{v_file}" -i "{a_file}" -map 0:v -map 1:a -c:v copy -shortest "{output_file}"'
        print(f"\nExecuting: {cmd}")
        subprocess.run(cmd, shell=True)
        return output_file
        
    elif implementation == "audio_visual":
        if not input_files: raise ValueError("No input file.")
        a1 = input_files[0]
        visual_type = inp.get("visual_type", "waveform")
        if not output_file:
            if visual_type == "waveform": output_file = "waveform.mp4"
            else: output_file = "spectrogram.png"
            
        if visual_type == "waveform":
            cmd = f'"{ffmpeg_path}" -y -i "{a1}" -filter_complex "[0:a]showwaves=s=1280x720:mode=line[v]" -map "[v]" -c:v libx264 "{output_file}"'
        else:
            cmd = f'"{ffmpeg_path}" -y -i "{a1}" -lavfi showspectrumpic=s=1280x720 "{output_file}"'
        print(f"\nExecuting: {cmd}")
        subprocess.run(cmd, shell=True)
        return output_file

    elif implementation == "video_layer":
        # Composite multiple videos/PNGs into one frame.
        # Supports 3 modes (set by layer_mode param):
        #   tile  → quadrant tiling, base always visible (default)
        #   pip   → picture-in-picture, overlay shrunk to a corner
        #   blend → pixel-average blend, both videos ghosted together
        if not input_files:
            raise ValueError("No input files specified for layering.")
        if len(input_files) < 2:
            raise ValueError("At least 2 files are required for layering.")

        output_file = output_file or "layered_output.mp4"
        layer_mode  = inp.get("layer_mode", "tile") or "tile"
        pip_pos     = inp.get("pip_position", "bottom-right") or "bottom-right"
        blend_w     = float(inp.get("blend_opacity") or 0.5)
        blend_w     = max(0.0, min(1.0, blend_w))   # clamp to [0, 1]

        IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"}
        VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}

        # Build -i input flags (images need -loop 1 to stay for full duration)
        input_args_parts = []
        for f in input_files:
            ext = os.path.splitext(f.lower())[1]
            if ext in IMAGE_EXTS:
                input_args_parts.append(f'-loop 1 -i "{f}"')
            else:
                input_args_parts.append(f'-i "{f}"')
        input_args = " ".join(input_args_parts)

        # Track audio sources
        audio_indices = []
        ext0 = os.path.splitext(input_files[0].lower())[1]
        if ext0 in VIDEO_EXTS and has_audio_stream(input_files[0], ffmpeg_path):
            audio_indices.append(0)

        filter_parts = []

        # ── Scale base to ≤1920×1080 ──────────────────────────────────────
        filter_parts.append(
            "[0:v]scale='min(1920,iw)':'min(1080,ih)'"
            ":force_original_aspect_ratio=decrease,"
            "pad=ceil(iw/2)*2:ceil(ih/2)*2[base]"
        )
        last_label = "base"

        if layer_mode == "blend":
            # ── BLEND MODE: weighted mix of 2 streams ─────────────────────
            # blend_w = weight of base (first video). overlay gets (1 - blend_w).
            # e.g. blend_w=0.7 → base at 70%, overlay at 30%
            overlay_w = round(1.0 - blend_w, 4)
            filter_parts.append(
                f"[1:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
                f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2[blend_top]"
            )
            filter_parts.append(
                f"[base][blend_top]blend=all_expr='A*{blend_w}+B*{overlay_w}'[v1]"
            )
            last_label = "v1"
            ext1 = os.path.splitext(input_files[1].lower())[1]
            if ext1 in VIDEO_EXTS and has_audio_stream(input_files[1], ffmpeg_path):
                audio_indices.append(1)

        elif layer_mode == "pip":
            # ── PIP MODE: overlay shrunk to 25% in a corner ───────────────
            pos_map = {
                "top-left":     "10:10",
                "top-right":    "W-w-10:10",
                "bottom-left":  "10:H-h-10",
                "bottom-right": "W-w-10:H-h-10",
            }
            for i in range(1, len(input_files)):
                ext = os.path.splitext(input_files[i].lower())[1]
                sl  = f"layer{i}s"
                ol  = f"v{i}"
                pos = pos_map.get(pip_pos, "W-w-10:H-h-10")

                if ext in IMAGE_EXTS:
                    filter_parts.append(
                        f"[{i}:v]scale='min(iw,480)':'min(ih,270)',"
                        f"pad=ceil(iw/2)*2:ceil(ih/2)*2[{sl}]"
                    )
                else:
                    filter_parts.append(
                        f"[{i}:v]scale=480:270:force_original_aspect_ratio=decrease,"
                        f"pad=ceil(iw/2)*2:ceil(ih/2)*2[{sl}]"
                    )
                    if has_audio_stream(input_files[i], ffmpeg_path):
                        audio_indices.append(i)

                filter_parts.append(
                    f"[{last_label}][{sl}]overlay={pos}:format=auto[{ol}]"
                )
                last_label = ol

        else:
            # ── TILE MODE (default): quadrant tiling ──────────────────────
            tile_positions = ["0:0", "W/2:0", "0:H/2", "W/2:H/2"]
            for i in range(1, len(input_files)):
                ext = os.path.splitext(input_files[i].lower())[1]
                sl  = f"layer{i}s"
                ol  = f"v{i}"
                pos = tile_positions[(i - 1) % len(tile_positions)]

                if ext in IMAGE_EXTS:
                    filter_parts.append(
                        f"[{i}:v]scale='min(iw,960)':'min(ih,540)',"
                        f"pad=ceil(iw/2)*2:ceil(ih/2)*2[{sl}]"
                    )
                else:
                    filter_parts.append(
                        f"[{i}:v]scale=960:540:force_original_aspect_ratio=decrease,"
                        f"pad=ceil(iw/2)*2:ceil(ih/2)*2[{sl}]"
                    )
                    if has_audio_stream(input_files[i], ffmpeg_path):
                        audio_indices.append(i)

                filter_parts.append(
                    f"[{last_label}][{sl}]overlay={pos}:format=auto[{ol}]"
                )
                last_label = ol

        # ── Audio mix ─────────────────────────────────────────────────────
        if len(audio_indices) > 1:
            audio_inputs = "".join(f"[{idx}:a]" for idx in audio_indices)
            filter_parts.append(
                f"{audio_inputs}amix=inputs={len(audio_indices)}:duration=longest[aout]"
            )
            audio_map = '-map "[aout]"'
        elif len(audio_indices) == 1:
            audio_map = f"-map {audio_indices[0]}:a"
        else:
            audio_map = ""

        filter_complex = ";".join(filter_parts)

        # Use -t instead of -shortest to avoid infinite loops with -loop 1 PNGs
        base_duration = get_video_duration(input_files[0], ffmpeg_path)
        duration_flag = f"-t {base_duration:.3f}" if base_duration else "-shortest"

        cmd = (
            f'"{ffmpeg_path}" -y {input_args} '
            f'-filter_complex "{filter_complex}" '
            f'-map "[{last_label}]" {audio_map} '
            f'-c:v libx264 -c:a aac {duration_flag} '
            f'"{output_file}"'
        )
        print(f"\nMode: {layer_mode} | Position: {pip_pos} | Opacity: base={blend_w*100:.0f}% overlay={round(1-blend_w,4)*100:.0f}%")
        print(f"\nExecuting: {cmd}")
        subprocess.run(cmd, shell=True)
        return output_file

    # Finally, fallback to simple templates
    if implementation in FFMPEG_COMMANDS:
        template = FFMPEG_COMMANDS[implementation]
        
        # Handle desktop screenshot special case (no input files provided)
        if implementation == "take_screenshot" and not input_files:
            output_file = output_file or "screenshot.png"
            cmd = f'"{ffmpeg_path}" -y -f gdigrab -framerate 1 -i desktop -frames:v 1 "{output_file}"'
            print(f"\nExecuting: {cmd}")
            subprocess.run(cmd, shell=True)
            return output_file
            
        if not input_files:
            raise ValueError("No input file specified.")
            
        if output_file is None:
            input_file = input_files[0]
            if implementation == "extract_audio":
                output_file = str(Path(input_file).with_suffix(".mp3"))
            elif implementation == "take_screenshot":
                output_file = str(Path(input_file).with_suffix(".png"))
            elif implementation == "resize_video":
                p = Path(input_file)
                output_file = str(p.with_name(p.stem + "_resized" + p.suffix))
                
        command = template
        command = command.replace("{ffmpeg_path}", ffmpeg_path)
        command = command.replace("{input_file}", input_files[0])
        command = command.replace("{output_file}", output_file)
        if "width" in inp: command = command.replace("{width}", str(inp["width"]))
        if "height" in inp: command = command.replace("{height}", str(inp["height"]))
        
        print(f"\nExecuting: {command}")
        subprocess.run(command, shell=True)
        return output_file
        
    raise ValueError(f"Unknown ffmpeg implementation: {implementation}")