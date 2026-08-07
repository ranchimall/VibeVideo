"""
Video Focus-Point Coordinate Picker
=====================================

Interactive tool to build a MOVING focus-point track for a video: play
it, pause wherever you like, click on the subject you want to track.
Each click is logged and the video automatically jumps forward
INTERVAL_SECONDS and pauses again, ready for you to click the subject's
new position. Repeat through the section you care about.

Produces a CSV of (time_seconds, focus_x, focus_y) rows — a TRACK,
as opposed to one static point — which is what a subject that moves
around the frame actually needs.

Requires opencv-python:
    pip install opencv-python

CONTROLS
---------
    SPACE     Play / pause
    Left click  Mark the point at the current frame, then auto-advance
                by INTERVAL_SECONDS and pause
    D         Step forward one frame (while paused)
    A         Step backward one frame (while paused)
    U         Undo the last marked point
    S         Save points to CSV now (also auto-saves on quit)
    Q / ESC   Save and quit

RUN:
    python coordinate_picker.py
"""

import cv2
import os
import csv

# ---------------------------------------------------------------------------
# CONFIG — edit path and interval here
# ---------------------------------------------------------------------------
VIDEO_PATH = r"C:\Users\saket\Documents\Manim\satoshi_edits_video.mp4"

# How far to auto-advance after each click.
INTERVAL_SECONDS = 0.5

OUTPUT_CSV = os.path.join(
    os.path.dirname(os.path.abspath(VIDEO_PATH)), "focus_track.csv"
)

WINDOW_NAME = "Focus Point Picker"

# Display window is shrunk to fit the screen if the video is large;
# clicks are converted back to native-resolution fractions automatically,
# so the CSV output is always correct regardless of this scaling.
DISPLAY_MAX_WIDTH = 900
DISPLAY_MAX_HEIGHT = 900


# ---------------------------------------------------------------------------
# STATE
# ---------------------------------------------------------------------------
class State:
    def __init__(self, cap):
        self.cap = cap
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.native_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.native_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.frame_idx = 0
        self.playing = False
        self.points = []  # (time_seconds, focus_x, focus_y)
        self.display_scale = min(
            DISPLAY_MAX_WIDTH / self.native_w,
            DISPLAY_MAX_HEIGHT / self.native_h,
            1.0,
        )
        self.current_frame = None
        self.dirty = False  # unsaved changes since last save


def seek(state, frame_idx):
    frame_idx = max(0, min(frame_idx, state.total_frames - 1))
    state.frame_idx = frame_idx
    state.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ok, frame = state.cap.read()
    if ok:
        state.current_frame = frame
    return ok


def advance_frames(state, n_frames):
    seek(state, state.frame_idx + n_frames)


def time_seconds(state):
    return state.frame_idx / state.fps


def render(state):
    frame = state.current_frame
    if frame is None:
        return None
    disp = cv2.resize(
        frame, None, fx=state.display_scale, fy=state.display_scale,
        interpolation=cv2.INTER_AREA,
    )
    t = time_seconds(state)
    status = (
        f"t={t:6.2f}s  frame={state.frame_idx}/{state.total_frames}  "
        f"points={len(state.points)}  {'PLAYING' if state.playing else 'PAUSED'}"
    )
    cv2.rectangle(disp, (0, 0), (disp.shape[1], 26), (0, 0, 0), -1)
    cv2.putText(disp, status, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (255, 255, 255), 1, cv2.LINE_AA)

    # Show the most recently marked point so you can see where you last
    # clicked relative to the current frame.
    if state.points:
        last_t, fx, fy = state.points[-1]
        px = int(fx * disp.shape[1])
        py = int(fy * disp.shape[0])
        cv2.circle(disp, (px, py), 6, (0, 255, 0), 2)
        cv2.putText(disp, f"last @ {last_t:.2f}s", (px + 8, py - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1, cv2.LINE_AA)

    return disp


def on_mouse(event, x, y, flags, state):
    if event != cv2.EVENT_LBUTTONDOWN or state.current_frame is None:
        return

    disp_w = int(state.native_w * state.display_scale)
    disp_h = int(state.native_h * state.display_scale)
    focus_x = min(max(x / disp_w, 0.0), 1.0)
    focus_y = min(max(y / disp_h, 0.0), 1.0)

    t = time_seconds(state)
    state.points.append((round(t, 3), round(focus_x, 4), round(focus_y, 4)))
    state.dirty = True
    print(f"Marked: t={t:.2f}s  focus=({focus_x:.4f}, {focus_y:.4f})   "
          f"[{len(state.points)} points total]")

    # Pause and auto-advance to the next sample point.
    state.playing = False
    advance_n = max(1, round(INTERVAL_SECONDS * state.fps))
    advance_frames(state, advance_n)


def save_csv(state):
    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time_seconds", "focus_x", "focus_y"])
        for row in sorted(state.points):
            writer.writerow(row)
    state.dirty = False
    print(f"Saved {len(state.points)} points to: {OUTPUT_CSV}")


def undo(state):
    if state.points:
        removed = state.points.pop()
        state.dirty = True
        print(f"Undid: {removed}")


# ---------------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------------
def main():
    if not os.path.isfile(VIDEO_PATH):
        raise FileNotFoundError(
            f"Video file not found: {VIDEO_PATH}\n"
            f"Update VIDEO_PATH at the top of this script."
        )

    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {VIDEO_PATH}")

    state = State(cap)
    seek(state, 0)

    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, on_mouse, state)

    frame_delay_ms = max(1, int(1000 / state.fps))

    print("Controls: SPACE=play/pause  click=mark+advance  "
          "D=step fwd  A=step back  U=undo  S=save  Q/ESC=save & quit")

    while True:
        disp = render(state)
        if disp is not None:
            cv2.imshow(WINDOW_NAME, disp)

        wait_ms = frame_delay_ms if state.playing else 30
        key = cv2.waitKey(wait_ms) & 0xFF

        if key == ord(' '):
            state.playing = not state.playing
        elif key == ord('d'):
            state.playing = False
            advance_frames(state, 1)
        elif key == ord('a'):
            state.playing = False
            advance_frames(state, -1)
        elif key == ord('u'):
            undo(state)
        elif key == ord('s'):
            save_csv(state)
        elif key in (ord('q'), 27):  # Q or ESC
            break

        if state.playing:
            ok = seek(state, state.frame_idx + 1)
            if not ok or state.frame_idx >= state.total_frames - 1:
                state.playing = False

    if state.points:
        save_csv(state)

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
