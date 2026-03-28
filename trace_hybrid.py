import json
from export_etme_data import parse_midi, HarmonizedParticle
from harmonic_regime_detector import HarmonicRegimeDetector
from voice_threader import VoiceThreader

# Extract keyframes from chunk 3
midi_file = "pathetique_test_chunk3.mid"
keyframes = parse_midi(midi_file)

# Run EXACTLY hybrid + 0.5
detector = HarmonicRegimeDetector(
    break_angle=15.0, 
    min_break_mass=0.75, 
    merge_angle=20.0, 
    angle_map="dissonance", 
    break_method="hybrid", 
    jaccard_threshold=0.5
)
regime_frames = detector.process(keyframes)

# Prepare particles
particles = []
for f in regime_frames:
    time_ms = f['Time (ms)']
    for p in f['Particles']:
        particles.append(HarmonizedParticle(
            pitch=p['pitch'],
            velocity=p['velocity'],
            onset=p['onset'],
            duration=p['duration'],
            regime_id=f['Regime_ID']
        ))

# Thread them
threader = VoiceThreader(max_voices=4)
particles = threader.thread_particles(particles, regime_frames)

print("=== Hybrid 0.5 at 2100-2400ms ===")
for p in sorted(particles, key=lambda x: (x.onset, -x.pitch)):
    if 2100 <= p.onset <= 2400:
        print(f"{p.onset}ms: {p.pitch} => Voice {p.voice_id + 1}")
