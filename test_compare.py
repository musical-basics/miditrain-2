import sys
sys.path.insert(0, '/Users/lionelyu/Documents/New Version/miditrain-2')
from export_etme_data import midi_to_particles
from voice_threader import VoiceThreader

# The only difference between 337 and 65 overlaps was the assignment target_threads list.
# 337 logic: list(best_subset) if best_subset else available_threads[:num_notes]
# 65 logic: chord_assignment (V1, V2, V3, V4 mapping)

class TestCompare(VoiceThreader):
    pass
# I don't need a python script, I can just analyze the logic.
