import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from engines.audacity_engine import AudacityEngine

audacity = AudacityEngine()

audacity.connect()

audacity.import_audio(
    r"C:\Users\saket\Documents\GitHub\VibeVideo\audio.mp3"
)

audacity.select_all()

audacity.normalize()

audacity.export(
    r"C:\Users\saket\Documents\GitHub\VibeVideo\output.wav"
)

print("Done!")