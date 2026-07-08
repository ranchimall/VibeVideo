# This is AI Blockchain Contract project
This project is part of projectai token system of AI Blockchain Contract series of RanchiMall. A blockchain contract is a governance structure on the blockchain which enables human led supervision over blockchain projects, as opposed to Corporate incorporation in traditional businesses and purely automated Smartcontracts in DAOs (Distributed Autonomous Organisation). Funding for Blockchain Contract comes directly on blockchain.

## AIBC (Artificial Intelligence Blockchain Contract):
[AIBC Website](https://ranchimall.github.io/aibc)

# VibeVideo

An intelligent, natural language-driven command-line interface for video and audio editing. 


## Directory Structure

- **`documents/`**: Contains text files that act as the canonical source-of-truth for all capabilities. These are parsed and stored in ChromaDB on first startup, then indexed by FAISS for fast in-memory semantic search.
- **`engines/`**: Houses the backend integration scripts (`ffmpeg_engine.py`, `audacity_engine.py`, `insightface_engine.py`, `ytdl.py`) that actually execute commands on media files.
- **`mcp/`**: Contains the Model Context Protocol (MCP) logic (`chroma_store.py`, `capability_resolver.py`, `executor.py`, `registry.py`) that seeds ChromaDB, builds the FAISS index, extracts parameters from commands, and dispatches instructions to engines.
- **`models/`**: Stores downloaded machine learning weights (e.g., InsightFace ONNX model) and the ChromaDB persistent vector database (`chroma_db/` — gitignored).
- **`sample_media/`**: The designated working directory to place your videos, audio, and images for editing.
- **`tests/`**: Contains automated scripts to verify the CLI's capabilities.

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

You can install all required and optional dependencies in one go using the `requirements.txt` file:

```bash
pip install -r requirements.txt
```

> [!NOTE]
> The editor uses the `imageio-ffmpeg` package to automatically fetch and use the correct FFmpeg executable, so you do not need to manually install or configure FFmpeg in your system path for basic tasks!

*(This also installs dependencies for the **Video Face Swapping** feature like `insightface` and `onnxruntime`, and `yt-dlp` for downloading YouTube videos.)*

### 4. Optional Third-Party Software
- **Audacity**: Required **ONLY** if you plan to use the `normalize audio` command. You must have the Audacity desktop application installed and actively running on your PC with the `mod-script-pipe` module enabled in its settings (Edit -> Preferences -> Modules).



---

## How to Use

1. Place the media files you want to edit in the same directory as `vibevideo.py`.
2. Start the interactive console:
   ```bash
   python vibevideo.py
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

The table below summarizes the natural language commands supported. On first startup, all capabilities are seeded from `documents/*.txt` into a **ChromaDB** persistent vector store (organized into 4 collections: `video_editing`, `audio_editing`, `ai_tools`, `web_tools`). **FAISS** then indexes these for fast in-memory semantic search on every command.

| Intent (FAISS Category) | Sample Prompts / Commands | Parsed Parameters | Output File / Result | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| **`screenshot`** | `take a screenshot`, `capture screenshot as capture.png` | `filename` | Screenshot of the desktop (default: `screenshot.png`) | Core FFmpeg |
| **`screen_record`** | `record screen at 60 fps for 10 seconds as desktop.mp4` | `fps`, `duration`, `filename` | Desktop screen recording (default: `recording.mp4`) | Core FFmpeg |
| **`screen_record_audio`**| `record screen with microphone as webinar.mp4` | `fps`, `duration`, `filename` | Screen recording with system audio/mic (default: `recording_audio.mp4`) | Core FFmpeg |
| **`video_clip`** | `clip f1 from 00:05 to 00:15 into cut.mp4`, `trim file2 for 10 seconds` | `input_files`, `output_file`, `start_time`, `end_time`, `duration` | Trimmed video clip (default: `<input>_clipped.<ext>`) | Core FFmpeg |
| **`resize_video`** | `resize video to 1920x1080 as large.mp4`, `scale video to 640x480` | `input_files`, `output_file`, `width`, `height` | Video resized to new dimensions (default: `<input>_resized.<ext>`) | Core FFmpeg |
| **`video_merge`** | `merge f1 and f2 using slideleft transition as final.mp4`, `combine file1.mp4 and file2.mp4` | `input_files`, `output_file`, `transition` | Merged video. If 2 videos and transition defined, applies xfade. (default: `merged.mp4`) | Core FFmpeg |
| **`video_layer`** | `overlay bird.mp4 and hud.png top right and vfx.mp4 bottom left` | `input_files`, `output_file`, `layer_positions` | Composited video layers (default: `layered_output.mp4`) | Core FFmpeg |
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
| **`audio_normalize`**| `normalize audio f2.mp3`, `normalize loudness of f2` | `input_files`, `output_file` | Audio file with normalized volume (default: `<input>_normalized.<ext>`) | Audacity (App must be running) |
| **`download_youtube`**| `download a youtube video`, `download youtube link` | `url`, `quality`, `start_time`, `end_time` | Downloaded YouTube video clip (default: `<video_title>.mp4`) | yt-dlp |

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
* **Layer Mode**: Extracted using the keyword `overlay`. Default is `tile` (quadrant layout).
  * **Universal Overlay:** Use keyword `overlay` to stack multiple files. The engine intelligently auto-detects transparency (Alpha for PNG vs Screen for MP4 VFX).
    * **Base Video:** The *first* file in the command acts as the **Base** (background).
    * **Overlays:** Every file listed after the base acts as a **Layer** placed on top.
* **Per-File Layer Positions**: Extracted using keywords `top left`, `top right`, `bottom left`, `bottom right`, `full`. 
  * You can assign a specific position to *each individual layer* by writing the position immediately after the filename.
  * If you specify a corner (e.g. `top right`), the engine automatically scales that specific layer down to a Picture-in-Picture (PiP) size and pads it into the corner.
  * If you don't specify a corner, the layer is scaled to full-screen (1920x1080).
  * *Example:* `overlay base.mp4 and hud.png top right and vfx.mp4 bottom left`

---

## Advanced: Universal Overlay Engine
The `overlay` command acts as a universal, intelligent compositor that allows you to build complex multi-layered VFX scenes in a single sentence.

### The Base Video vs Layers
The **very first file** you specify is always the **Base** (the background). All subsequent files are processed as layers stacked on top.

### Smart Alpha vs Screen Detection
You don't need to specify whether a file has a black background or a transparent background. 
* If a layer is an `.mp4`, the engine automatically converts it to `gbrp` color space and applies a **Screen Blend** (perfectly erasing the black background).
* If a layer is a `.png` or `.mov`, it automatically applies standard **Alpha Transparency**.

### Layer Positioning (PiP vs Full-Screen)
By default, all layers are scaled to full-screen 1080p. However, you can convert any layer into a Picture-in-Picture (PiP) by specifying a corner immediately after the filename.

**Example Command:**
```text
overlay bird.mp4 and hud.png top right and fire.mp4 bottom left and glitch.mp4
```
**How it processes:**
1. `bird.mp4` $\rightarrow$ First file, so it acts as the **Base** video (background).
2. `hud.png top right` $\rightarrow$ Detected as a PNG (Alpha). Position specified, so it is shrunk to 25% size and placed in the **Top Right** corner.
3. `fire.mp4 bottom left` $\rightarrow$ Detected as an MP4 (Screen blend erases black). Position specified, so it is shrunk to 25% size and placed in the **Bottom Left** corner.
4. `glitch.mp4` $\rightarrow$ No position specified! Detected as an MP4 (Screen blend). Scaled to **Full Screen 1080p** and layered over everything.

---

