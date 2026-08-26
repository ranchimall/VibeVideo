# VibeVideo

An intelligent, natural language-driven command-line interface for video and audio editing. 


## Directory Structure

- **`documents/`**: Contains text files describing tool capabilities, which are chunked and embedded by FAISS to understand natural language intent.
- **`engines/`**: Houses the backend integration scripts (`ffmpeg_engine.py`, `audacity_engine.py`, `insightface_engine.py`, `ytdl.py`) that actually execute commands on media files.
- **`mcp/`**: Contains the Model Context Protocol (MCP) logic (`capability_resolver.py`, `executor.py`, `registry.py`) that extracts parameters, queries the FAISS index, and dispatches instructions to engines.
- **`models/`**: Stores downloaded machine learning weights (e.g., InsightFace) and the serialized FAISS vector index.
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

The table below summarizes the natural language commands supported by the FAISS index, the parameters they parse, and the tools they trigger:

| Intent (FAISS Category) | Sample Prompts / Commands | Parsed Parameters | Output File / Result | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| **`screenshot`** | `take a screenshot`, `capture screenshot as capture.png` | `filename` | Screenshot of the desktop (default: `screenshot.png`) | Core FFmpeg |
| **`screen_record`** | `record screen at 60 fps for 10 seconds as desktop.mp4` | `fps`, `duration`, `filename` | Desktop screen recording (default: `recording.mp4`) | Core FFmpeg |
| **`screen_record_audio`**| `record screen with microphone as webinar.mp4` | `fps`, `duration`, `filename` | Screen recording with system audio/mic (default: `recording_audio.mp4`) | Core FFmpeg |
| **`video_clip`** | `clip f1 from 00:05 to 00:15 into cut.mp4`, `trim file2 for 10 seconds` | `input_files`, `output_file`, `start_time`, `end_time`, `duration` | Trimmed video clip (default: `<input>_clipped.<ext>`) | Core FFmpeg |
| **`resize_video`** | `resize video to 1920x1080 as large.mp4`, `scale video to 640x480` | `input_files`, `output_file`, `width`, `height` | Video resized to new dimensions (default: `<input>_resized.<ext>`) | Core FFmpeg |
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

---

# VibeVideo — Visual Chessboard Editor (`app66.py`)

`app66.py` is a **web-based visual video editor** built on [Gradio](https://www.gradio.app/) that runs the `vibevideo.py` NLP engine behind a point-and-click interface. It lets you arrange clips on a visual "chessboard" grid (rows = tracks), trim/move/copy/remove them non-destructively, composite picture-in-picture overlays, preview any combination instantly, export at 1080p — and drive everything with free-text natural language commands.

## ✨ Feature Highlights

- 📼 **Media Library Grid** — upload videos, audio, images, and subtitles; browse them as clickable thumbnails with sorting (Date Created / Name / File Type).
- ♟️ **Working Grid (Chessboard)** — every clip lives as a tile on a grid. Each **row is an independent track**; each **column is the play order** within that row. Rows play their clips back-to-back, independently of other rows.
- 🎬 **One Shared Preview Box** — clip, row, full-grid, or custom-selection previews all render into a single player, and **exports replicate exactly what you previewed**.
- ✂️ **Non-destructive editing** — every edit (Add / Trim / Move / Copy / Remove) is an entry in an append-only *action log*. Nothing touches your source files, and **Undo** simply drops the last action.
- 🖼️ **Overlay compositing** — per-row or per-clip Picture-in-Picture (choose corner + size %), full-canvas **alpha overlays** that preserve real PNG transparency, layer priority (z-index) to choose the base layer, and per-row time shifts (±seconds).
- 🤖 **AI Command Assistant** — type commands in plain English (`"trim f1 from 5 to 10 seconds"`, `"join R0C0 and R1C0"`). Supports `file1` / `f1` / `[1]` shortcuts, direct grid-cell references (`R2C3`), `{files}` / `{time}` placeholders, and live streaming command logs.
- ⚡ **Background proxy pipeline** — videos are auto-transcoded to lightweight 854×480 proxies in a priority queue (what you click renders first), so previews stay fast even with large source files.

## 📋 Prerequisites

| Requirement | Details |
| :--- | :--- |
| **Python** | 3.10 or newer |
| **FFmpeg + ffprobe** | Must both be installed and available on your system `PATH`. (The editor's own preview/proxy/export pipeline calls `ffmpeg` and `ffprobe` directly.) Download a full build from [ffmpeg.org](https://ffmpeg.org/download.html) or `winget install Gyan.FFmpeg`. Verify with `ffmpeg -version` and `ffprobe -version`. |
| **Internet connection** | Needed once on launch — the app exposes a public `*.gradio.live` share link, and the AI engine downloads sentence-embedding models on first run. |

## 🚀 Installation & Setup

### 1. Clone and enter the project
```bash
git clone https://github.com/ranchimall/VibeVideo.git
cd VibeVideo
```

### 2. Create and activate a virtual environment

**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**Windows (CMD):**
```bat
python -m venv venv
venv\Scripts\activate.bat
```

**Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
pip install gradio pandas
```

> [!NOTE]
> `gradio` and `pandas` are required specifically by `app66.py` and are not covered by the base `requirements.txt`. All other packages (`sentence-transformers`, `faiss-cpu`, `imageio-ffmpeg`, etc.) are shared with the CLI engine.

### 4. Run the editor
```bash
python app66.py
```

On startup you will see:
```text
Running on local URL:  http://127.0.0.1:7860
Running on public URL: https://xxxxx.gradio.live
```

Open either URL in your browser. The **local** URL works offline on your machine; the **public** `gradio.live` link lets you open the editor from anywhere (handy for sharing/remote access).

> [!TIP]
> First launch may take a minute: the AI engine loads its embedding model and scans `sample_media/`. Videos found in the library get their proxies generated in the background — click a tile and the app will show *"Media is loading, please wait…"* until its proxy is ready.

## 🗂️ Files & Folders Created

| Path | Purpose |
| :--- | :--- |
| `sample_media/` | Your media library. Anything placed here is auto-scanned into the app on startup, and all AI command outputs land here too. |
| `sample_media/proxies/` | Auto-generated 854×480 H.264 preview proxies (one per video, reused across sessions). |
| `%TEMP%\vibevideo_thumbnails\` | Cached JPEG thumbnails shown in the Library Grid. |
| `%TEMP%\vibevideo_render_cache\` | Cached preview segment renders (keyed by a render-logic version, so stale files are never served). |
| `%TEMP%\vibevideo_exports\` | Final exported files — grab your finished video here. |

All cache/temp folders are safe to delete at any time; they rebuild automatically.

## 🖥️ Using the Interface

The app has two tabs.

### Tab 1 — Visual Chessboard Editor

```
┌─────────────────────────┬──────────────────────────────┐
│  AVAILABLE LIST         │  WORKING GRID + ACTIONS      │
│  • Upload media         │  • The chessboard            │
│  • Library thumbnail    │  • Add / Trim / Move /       │
│    grid (click tiles)   │    Copy / Remove / Undo      │
│  • AI Command panel     │  • Overlays, arrows, shifts  │
├─────────────────────────┴──────────────────────────────┤
│  PREVIEW BOX (one shared video player + status)        │
│  Row Preview · Grid Preview · Custom Selection · Export│
└─────────────────────────────────────────────────────────┘
```

#### Step 1 — Add media to the Library (left column)
1. Click **Add media** and pick one or more files (or just drop files into `sample_media/` before launching).
2. Supported types: **video** (.mp4 .mkv .avi .mov .webm), **audio** (.mp3 .wav .aac .flac .m4a .ogg), **image** (.png .jpg .jpeg .gif .webp .bmp), **subtitle** (.srt .vtt .ass .sub).
3. Tiles appear as thumbnails. **Click a tile** to select it — selecting automatically places it onto the Working Grid; **click again to deselect** and remove it. Use the sort dropdowns to reorder the view.

#### Step 2 — Arrange clips on the Working Grid (right column)
- **Rows are tracks, columns are order.** Row 0 plays its clips left-to-right, then Row 1 plays its own clips, etc. Rows do *not* share a timeline — each plays independently (great for building parallel layers to composite).
- Pick a target **Row number** and **Column** (leave blank to auto-append), then use:
  - **Add to Working Grid →** — place the selected library file.
  - **Trim** — set new In/Out points (in seconds) for the target clip.
  - **Move / Copy / Remove** — restructure the grid. Arrow buttons swap a clip with its neighbor; **Copy** duplicates a clip to another row.
  - **Undo** — removes the last action (fully non-destructive).
- **Click any clip tile** to make it the *Target clip instance*, **click a row label (R0, R1…)** to select that row, and **tap the small ＋/✓ badges** on tiles, row headers, or column headers to build a **Custom Selection** (the corner button selects/deselects everything).

#### Step 3 — Composite with overlays (optional)
For rows above the base layer you can set **PIP overlays**: choose a corner (top-right, top-left, bottom-left, bottom-right, center) and a width percentage, per **row** or per individual **clip**. Special modes:
- **Full-canvas overlay** — alpha-composites the row/clip over whatever is beneath, preserving real transparency (e.g. a PNG logo's transparent background).
- **Layer priority (z-index)** — among visible rows, the one with the lowest priority number becomes the full-canvas base layer; all others overlay on top.
- **Row shift** — offset an entire row's start time by ± seconds.

#### Step 4 — Preview and export
Every preview scope writes into the **one shared Preview box**:
- **Clip preview** — the selected clip alone (with its own selection bar).
- **Row preview** — one whole track concatenated back-to-back.
- **Grid preview** — the full composite exactly as layered (base + overlays).
- **Custom Selection preview** — any mix of picked clips/rows/columns.

Use the **selection bar** under the preview to mark points/spans with the syntax `10-15, 22.3, 40-45` (bands and single time-points in seconds, freely combined), then preview or export just those ranges.

When you're happy, hit **Export** — renders at **1920×1080** full quality and saves to `%TEMP%\vibevideo_exports\` with the path shown in the status line.

### Tab 2 — AI Command Assistant

Type plain-English commands and press Run. The same engine powering the [CLI](#how-to-use) executes them against your library:

```text
clip f1 from 00:05 to 00:15 into highlight.mp4
merge f1 and f2 using fade transition as intro.mp4
extract audio from f2.mp3
download youtube https://youtu.be/dQw4w9WgXcQ as mp3
delete 10-20 from f1
```

Extras unique to the GUI:
- **Grid cell references** — refer to clips by their chessboard position: `"Join R0C0 and R1C0"` resolves `R0C0`/`R1C0` to whatever currently sits in those cells.
- **File shortcuts** — `file1`, `f1`, `[1]` map to library entries (see the *Valid Names in Commands* mapping table).
- **Live logs** — command progress streams into the *AI Command Logs* box in real time, including which tier/matched capability was used.
- Generated outputs are auto-ingested back into the Library and loaded into the shared Preview box.

In Tab 1's **AI Command panel**, the chessboard itself feeds the command: choose a scope (**Clip** / **Selected Clips** / **Row** / **Entire Grid**) and the resolved files are injected automatically — use the `{files}` and `{time}` placeholders in your command text to control exactly where filenames and your selection-bar timings go, e.g. `trim {files} {time}` with selection `10-15`.

## 🔧 Troubleshooting

| Problem | Fix |
| :--- | :--- |
| `ffmpeg` / `ffprobe` not found | Install a **full** FFmpeg build (both binaries ship together) and ensure it's on `PATH`; restart your terminal. `imageio-ffmpeg` alone is not enough for this app because `ffprobe` is used for duration detection. |
| Preview says *"Media is loading, please wait…"* | The video's proxy is still being generated. Large files can take a while on first use; the app retries automatically (up to 10 minutes per file). Subsequent runs are instant (proxies are cached). |
| Port 7860 already in use | Another Gradio app is running. Stop it, or edit the final line of `app66.py`: `demo.queue().launch(share=True, server_port=7861, css=CUSTOM_CSS)`. |
| Public link didn't open | `share=True` requires internet access and occasionally fails behind strict firewalls/VPNs — use the local `http://127.0.0.1:7860` URL instead. |
| AI commands fail on first run | The sentence-transformer model downloads on first use (~100 MB). Wait for the download, then retry. Audacity must be running with `mod-script-pipe` enabled for `normalize audio` commands. |
| Old previews look wrong after editing render settings | Delete `%TEMP%\vibevideo_render_cache\` — cached renders are version-keyed, but clearing forces a clean rebuild. |

## 💡 Notes

- Editing is **non-destructive** — source files in `sample_media/` are never modified; exports always create new files.
- The grid grows automatically beyond its default 6×8 size as you add more clips.
- Image clips default to **3 seconds** each (adjustable via *Default image duration* at upload time); subtitle clips to 5 seconds.
- `app66.py` shares its AI/NLP core with `vibevideo.py`, so every CLI capability in the [Commands & Capabilities Reference](#commands--capabilities-reference) above works in the AI Assistant too.

---

