# VibeVideo

An intelligent, natural language-driven command-line interface for video and audio editing. 


---

## Getting Started

### 1. Prerequisites
To use all features of the editor, you will need **Python 3.8+** installed on your system.

### 2. Setting Up the Virtual Environment (venv)
It is highly recommended to run this project inside a Python Virtual Environment (`venv`) to keep your dependencies isolated. 

To configure and activate the environment on **Windows**:
```bash
# 1. Create the virtual environment (if not already created)
python -m venv venv

# 2. Activate the virtual environment
# For PowerShell:
.\venv\Scripts\Activate.ps1

# For Command Prompt (CMD):
.\venv\Scripts\activate.bat
```

Once activated, your terminal prompt will display `(venv)`.

### 3. Dependency Installation
Ensure your virtual environment is active, then install the required Python packages:

#### Core Dependencies (Required)
```bash
pip install sentence-transformers faiss-cpu numpy imageio-ffmpeg
```
> [!NOTE]
> The editor uses the `imageio-ffmpeg` package to automatically fetch and use the correct FFmpeg executable, so you do not need to manually install or configure FFmpeg in your system path for basic tasks!

#### Feature-Specific Dependencies (Optional)
To use the **Video Face Swapping** feature, you will need to install InsightFace and its dependencies:
```bash
pip install insightface onnxruntime opencv-python
```


---

## How to Use

1. Place the media files you want to edit in the same directory as [cli_ve.py]
2. Start the interactive console:
   ```bash
   python cli_ve.py
   ```
3. Upon startup, the editor will scan the directory and list all available media files, assigning them numbered shortcuts:
   ```text
   Available files:
     [1] holiday_clip.mp4
     [2] background_music.mp3
     [3] intro_logo.png
   ```
4. Enter commands using natural language. You can refer to files by their actual names or use shorthand placeholders:
   * **`file1`**, **`file2`** (or `file 1`, `file 2`)
   * **`f1`**, **`f2`**
   * **`[1]`**, **`[2]`**
5. Type `exit` or `quit` to close the editor.

---

## Commands & Capabilities Reference

The table below summarizes the natural language commands supported by the FAISS index, the parameters they parse, and the tools they trigger:

| Intent (FAISS Category) | Sample Prompts / Commands | Parsed Parameters | Output File / Result | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| **`screenshot`** | `take a screenshot`, `capture screenshot as capture.png` | `filename` | Screenshot of the desktop (default: `screenshot.png`) | Core FFmpeg |
| **`screen_record`** | `record screen at 60 fps for 10 seconds as desktop.mp4` | `fps`, `filename` | Desktop screen recording (default: `recording.mp4`) | Core FFmpeg |
| **`screen_record_audio`**| `record screen with microphone as webinar.mp4` | `fps`, `filename` | Screen recording with system audio/mic (default: `recording_audio.mp4`) | Core FFmpeg |
| **`video_clip`** | `clip f1 from 00:05 to 00:15 into cut.mp4`, `trim file2 for 10 seconds` | `input_files`, `output_file`, `start_time`, `end_time`, `duration` | Trimmed video clip (default: `<input>_clipped.<ext>`) | Core FFmpeg |
| **`video_merge`** | `merge f1 and f2 using slideleft transition as final.mp4`, `combine file1.mp4 and file2.mp4` | `input_files`, `output_file`, `transition` | Merged video. If 2 videos and transition defined, applies xfade. (default: `merged.mp4`) | Core FFmpeg |
| **`face_swap_video`** | `swap face in video.mp4 with face.jpg`, `replace face in f1 with f2` | `input_files`, `output_file` | Video with the face swapped seamlessly (default: `<input>_faceswap.<ext>`) | InsightFace, ONNXRuntime, OpenCV |
| **`audio_trim`** | `trim audio f2 from 10 to 30 seconds`, `cut f2 from 00:00:10 to 00:00:30` | `input_files`, `output_file`, `start_time`, `end_time`, `duration` | Trimmed audio file (default: `<input>_trimmed.<ext>`) | Core FFmpeg |
| **`audio_volume`** | `double volume of f2.mp3`, `make audio f2.wav quieter by volume 0.5` | `input_files`, `output_file`, `volume_level` | Adjusted volume audio/video file (default: `<input>_volume.<ext>`) | Core FFmpeg |
| **`audio_fade`** | `apply fade out of 3 seconds to f2.mp3`, `fade in f2.wav starting from 0 for 5 seconds` | `input_files`, `output_file`, `fade_type`, `fade_duration`, `start_time` | Audio file with fade-in/fade-out applied (default: `<input>_fade_<in/out>.<ext>`) | Core FFmpeg |
| **`audio_mix`** | `mix voice.mp3 and music.mp3`, `mix f2 and f3 as mixed.mp3` | `input_files`, `output_file` | Multi-track mixed audio file (default: `mixed.mp3`) | Core FFmpeg |
| **`audio_speed`** | `speed up sound f2 to 1.5x`, `slow down f2.mp3 to tempo 0.8` | `input_files`, `output_file`, `speed_multiplier` | Audio file with speed/tempo adjustment (default: `<input>_speed.<ext>`) | Core FFmpeg |
| **`audio_reverse`** | `reverse audio track f2.mp3`, `play song.mp3 backwards` | `input_files`, `output_file` | Audio track played backwards (default: `<input>_reversed.<ext>`) | Core FFmpeg |
| **`audio_extract`** | `extract audio from f1.mp4 to track.mp3`, `rip audio track from file1.mov` | `input_files`, `output_file` | Standalone audio track extracted from video (default: `<input>_extracted.mp3`) | Core FFmpeg |
| **`audio_replace`** | `replace audio in file1.mp4 with background.mp3`, `add backing music f2 to f1` | `input_files`, `output_file` | Video output combined with new audio input (default: `replaced_output.mp4`) | Core FFmpeg |
| **`audio_visual`** | `generate waveform video for f2.mp3`, `generate spectrogram image of f2` | `input_files`, `output_file`, `visual_type` | Waveform video (`.mp4`) or Spectrogram image (`.png`) | Core FFmpeg |

---

## Natural Language Parameter Syntax

The editor extracts details from your commands using a regular expression parser. Below are the patterns you can use to specify settings:

* **Filenames**: Matches any string ending in standard extensions (`.mp4`, `.mkv`, `.avi`, `.mov`, `.webm`, `.mp3`, `.wav`, `.png`, `.jpg`, `.jpeg`).
  * *Example:* `as final_edit.mp4`, `into backing_track.mp3`
* **Frames Per Second (FPS)**: Specified as a number followed by `fps`.
  * *Example:* `60 fps`, `30fps` (Default is `30`)
* **Start Time**: Extracted using keywords `from`, `start`, `starting`, `ss`, or `at` followed by a time signature (`HH:MM:SS`, `MM:SS`, or seconds).
  * *Example:* `from 00:01:30`, `starting at 45.5`
* **End Time**: Extracted using keywords `to`, `end`, or `ending` followed by a time signature.
  * *Example:* `to 00:02:15`, `ending at 90`
* **Duration**: Extracted using keywords `duration`, `for`, or `t` followed by a time signature or number of seconds.
  * *Example:* `for 15 seconds`, `duration 5`
* **Volume Level**: Extracted using the `volume` keyword followed by a number, or shorthands:
  * `double volume` $\rightarrow$ sets volume level to `2.0`
  * `half volume` $\rightarrow$ sets volume level to `0.5`
  * *Example:* `volume to 1.5`, `volume of 0.8`
* **Transitions**: Extracted using keywords `transition` or `using` followed by the transition name. Supports:
  * `fade`, `fadeblack`, `fadewhite`
  * `slideleft`, `slideright`, `slideup`, `slidedown`
  * `wipeleft`, `wiperight`, `wipeup`, `wipedown`
  * `circleopen`, `circleclose`, `pixelize`, `dissolve`
  * *Example:* `using slideleft`, `fade transition`
* **Speed/Tempo Multiplier**: Extracted using keywords `speed`, `tempo`, `speed up` (sets to `1.5`), or `slow down` (sets to `0.8`).
  * *Example:* `speed to 1.2x`, `tempo 1.3`
* **Audio Fade Duration & Type**: 
  * `fade in` $\rightarrow$ applies fade-in starting at the start time
  * `fade out` or `fade-out` $\rightarrow$ automatically calculates total audio length and fades out during the final seconds
  * Duration parsed via `fade ... of/for/duration X sec/seconds`
  * *Example:* `fade out for 5 seconds` (Default fade duration is `3.0`)
* **Audio Visualizer Type**:
  * Keyword `spectrogram` $\rightarrow$ renders static spectrogram image
  * Keyword `waveform` or default $\rightarrow$ renders animated waveform video

---

