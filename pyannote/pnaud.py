from pyannote.audio import Pipeline
import torch
import soundfile as sf
import os

token = os.environ["HF_TOKEN"]

# Load the pretrained pipeline
pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    token=token
)

# Optional: move to GPU if available
if torch.cuda.is_available():
    pipeline.to(torch.device("cuda"))

# Manually load audio to bypass torchcodec
audio_path = r"C:\Users\saket\Documents\pyannote\input.wav"
waveform, sample_rate = sf.read(audio_path, dtype="float32", always_2d=True)
waveform = torch.from_numpy(waveform.T)  # shape: (channels, time)

audio_input = {"waveform": waveform, "sample_rate": sample_rate}

# Run diarization
result = pipeline(audio_input, num_speakers=3)

# Debug: see what the result object actually contains
print("TYPE:", type(result))
print("ATTRIBUTES:", dir(result))

# Try the most likely attribute name for the actual annotation
diarization = result.speaker_diarization

# Print results: who spoke when
for turn, _, speaker in diarization.itertracks(yield_label=True):
    print(f"start={turn.start:.1f}s stop={turn.end:.1f}s speaker={speaker}")

# Optionally save as RTTM
with open("output.rttm", "w") as f:
    diarization.write_rttm(f)
