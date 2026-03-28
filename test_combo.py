import sys
sys.path.insert(0, '/Users/lionelyu/Documents/New Version/miditrain-2')
from export_etme_data import midi_to_particles
from voice_threader import VoiceThreader, VoiceThread
import itertools

class MockThreader(VoiceThreader):
    def thread_particles(self, particles, regime_frames):
        threads = [VoiceThread(i) for i in range(self.max_voices)]
        
        # Simulate base state at 250ms
        threads[0].last_pitch = 67
        threads[0].last_end_time = 250
        threads[0].ideal_pitch = 73
        
        threads[1].last_pitch = 63
        threads[1].last_end_time = 82
        threads[1].ideal_pitch = 62.3
        
        threads[2].last_pitch = 61
        threads[2].last_end_time = 82
        threads[2].ideal_pitch = 51.6
        
        threads[3].last_pitch = 58
        threads[3].last_end_time = 250
        threads[3].ideal_pitch = 41
        
        # Note Db5(73), Eb4(63), Db4(61) at 250ms
        p_first = particles[0]
        chord = particles[:3]
        chord[0].pitch = 73
        chord[0].onset = 250
        chord[0].duration = 750
        
        chord[1].pitch = 63
        chord[1].onset = 250
        chord[1].duration = 83
        
        chord[2].pitch = 61
        chord[2].onset = 250
        chord[2].duration = 83
        
        available_threads = []
        for thread in threads:
            if thread.last_pitch is None or chord[0].onset >= (thread.last_end_time - 40):
                available_threads.append(thread)
        print("Available threads:", [t.voice_id for t in available_threads])
        
        num_notes = len(chord)
        print(f"num={num_notes} avail={len(available_threads)}")
        
        if len(available_threads) > num_notes:
            best_subset = None
            lowest_cost = float('inf')
            for subset in itertools.combinations(available_threads, num_notes):
                cst = 0
                for ci, p in enumerate(chord):
                    cst += self._calculate_connection_cost(p, subset[ci], False)
                print(f"subset {[t.voice_id for t in subset]} -> {cst:.2f}")
                if cst < lowest_cost:
                    lowest_cost = cst
                    best_subset = subset
            print("best:", [t.voice_id for t in best_subset] if best_subset else None)
        return []

vt = MockThreader(4)
parts = midi_to_particles('pathetique_test_chunk3.mid')
vt.thread_particles(parts, [])
