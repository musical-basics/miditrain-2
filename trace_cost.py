import sys
sys.path.insert(0, '/Users/lionelyu/Documents/New Version/miditrain-2')
from export_etme_data import midi_to_particles, load_and_detect_regimes
from voice_threader import VoiceThreader
import itertools

class TraceThreader(VoiceThreader):
    def thread_particles(self, particles, regime_frames):
        threads = self.voice_threads
        particles.sort(key=lambda p: (p.onset, -p.pitch))
        
        i = 0
        while i < len(particles):
            p_first = particles[i]
            chord = [p_first]
            j = i + 1
            while j < len(particles) and particles[j].onset <= p_first.onset + 50:
                chord.append(particles[j])
                j += 1
            i = j
            chord.sort(key=lambda p: -p.pitch)
            
            if p_first.onset == 0:
                available_threads = []
                for t in threads:
                    if t.last_pitch is None or chord[0].onset >= (t.last_end_time - 40):
                        available_threads.append(t)
                
                print("--- 0ms ---")
                best = None
                lowest = float('inf')
                for subset in itertools.combinations(available_threads, len(chord)):
                    cst = 0
                    for ci, p in enumerate(chord):
                        cst += self._calculate_connection_cost(p, subset[ci], False)
                    print(f"Subset {[t.voice_id for t in subset]} -> {cst}")
                    if cst < lowest:
                        lowest = cst
                        best = subset
                print(f"Best: {[t.voice_id for t in best] if best else None}")
                
            for ci, p in enumerate(chord):
                target = threads[ci] # just blind ranking to advance state
                if target:
                    target.last_pitch = p.pitch
                    target.last_end_time = p.onset + p.duration
            
            if p_first.onset > 100: break
        return []

vt = TraceThreader(4)
parts = midi_to_particles('pathetique_test_chunk3.mid')
reg, _ = load_and_detect_regimes(parts)
vt.thread_particles(parts, reg)
