import sys
sys.path.insert(0, '/Users/lionelyu/Documents/New Version/miditrain-2')
from export_etme_data import midi_to_particles, load_and_detect_regimes
from voice_threader import VoiceThreader

orig_assign = VoiceThreader.thread_particles
def thread_parts(self, particles, regime_frames):
    return orig_assign(self, particles, regime_frames)
VoiceThreader.thread_particles = thread_parts

with open('voice_threader.py') as f: orig = f.read()

new_code = orig.replace(
    'p.voice_tag = \"Overflow (Chord)\"\\n                        continue',
    'p.voice_tag = \"Overflow (Chord)\"\\n                        print(f\"PARADOX: p.onset={p.onset} last={best_thread.last_end_time}\")\\n                        continue'
)

with open('voice_threader_paradox.py', 'w') as f: f.write(new_code)
import importlib.util
spec = importlib.util.spec_from_file_location(\"voice_threader\", \"voice_threader_paradox.py\")
vtm = importlib.util.module_from_spec(spec)
sys.modules[\"voice_threader\"] = vtm
spec.loader.exec_module(vtm)
from export_etme_data import export_analysis
export_analysis('pathetique_test_chunk3.mid', output_json='visualizer/public/test3.json', angle_map='dissonance', break_method='hybrid', jaccard_threshold=0.5)
