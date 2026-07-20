from kokoro import KPipeline
import soundfile as sf

text = "This is a sample of my voice for comparison."

# American English voices
pipeline_a = KPipeline(lang_code='a')
american_voices = ['af_heart', 'am_adam', 'am_fenrir', 'am_onyx', 'am_michael']

for voice in american_voices:
    generator = pipeline_a(text, voice=voice, speed=1.0)
    for i, (gs, ps, audio) in enumerate(generator):
        sf.write(f'{voice}.wav', audio, 24000)
        print(f"Saved {voice}.wav")

# British English voices
pipeline_b = KPipeline(lang_code='b')
british_voices = ['bm_george']

for voice in british_voices:
    generator = pipeline_b(text, voice=voice, speed=1.0)
    for i, (gs, ps, audio) in enumerate(generator):
        sf.write(f'{voice}.wav', audio, 24000)
        print(f"Saved {voice}.wav")


# Hindi voices
pipeline_h = KPipeline(lang_code='h')  # Hindi
hindi_voices = ['hf_alpha', 'hf_beta', 'hm_omega', 'hm_psi']

for voice in hindi_voices:
    generator = pipeline_h(text, voice=voice, speed=1.0)
    for i, (gs, ps, audio) in enumerate(generator):
        sf.write(f'{voice}.wav', audio, 24000)
        print(f"Saved {voice}.wav")        
