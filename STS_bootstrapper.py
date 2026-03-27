import math
from collections import deque

# ==========================================
# 1. HARMONIC REGIME DETECTOR (Physics Engine)
# ==========================================
INTERVAL_ANGLES = {
    "1": 0, "b2": 180, "2": 120, "b3": 270, "3": 60, "4": 330,
    "#4": 210, "5": 30, "b6": 300, "6": 90, "b7": 240, "7": 150
}
SEMITONE_MAP = {
    "1": 0, "b2": 1, "2": 2, "b3": 3, "3": 4, "4": 5, 
    "#4": 6, "5": 7, "b6": 8, "6": 9, "b7": 10, "7": 11
}

class HarmonicRegimeDetector:
    """Lightweight regime detector that only processes keyframe timestamps (not every 10ms)."""
    def __init__(self, buffer_ms=2000, debounce_ms=400):
        self.buffer_ms = buffer_ms
        self.debounce_ms = debounce_ms
        self.history = deque()
        self.prev_x, self.prev_y = 0.0, 0.0
        self.last_spike_time = -9999 
        self.prev_bass_id = None 

    def process_frame(self, current_time_ms, active_notes):
        self.history.append((current_time_ms, active_notes))
        while self.history and self.history[0][0] < current_time_ms - self.buffer_ms:
            self.history.popleft()

        current_bass_id = None
        if active_notes:
            lowest_note = min(active_notes, key=lambda n: (n[1], SEMITONE_MAP[n[0]]))
            current_bass_id = f"{lowest_note[0]}_{lowest_note[1]}"

        bass_changed = (current_bass_id and self.prev_bass_id and current_bass_id != self.prev_bass_id)
        self.prev_bass_id = current_bass_id

        x_total, y_total, weight_total = 0.0, 0.0, 0.0
        for _, frame_notes in self.history:
            for interval, octave, velocity in frame_notes:
                if velocity <= 0: continue
                weight = velocity / 127.0
                weight_total += weight
                angle_rad = math.radians(INTERVAL_ANGLES[interval])
                x_total += weight * math.cos(angle_rad)
                y_total += weight * math.sin(angle_rad)

        if weight_total == 0:
            self.prev_x, self.prev_y = 0.0, 0.0
            return {"Time (ms)": current_time_ms, "Hue": 0.0, "Sat (%)": 0.0, "V_vec": 0.0, "State": "Silence"}

        x_avg, y_avg = x_total / weight_total, y_total / weight_total
        v_vec = math.sqrt((x_avg - self.prev_x)**2 + (y_avg - self.prev_y)**2) * 100.0
        self.prev_x, self.prev_y = x_avg, y_avg

        final_hue = math.degrees(math.atan2(y_avg, x_avg))
        if final_hue < 0: final_hue += 360
        final_saturation = math.sqrt(x_avg**2 + y_avg**2) * 100.0

        state = "Stable"
        if final_saturation < 30.0:
            state = "Undefined / Gray Void"
        else:
            is_spiking = (v_vec > 25.0) or bass_changed
            if is_spiking and (current_time_ms - self.last_spike_time) >= self.debounce_ms:
                state = "TRANSITION SPIKE!"
                self.last_spike_time = current_time_ms
            elif final_saturation > 70.0 and v_vec < 8.0:
                state = "Regime Locked"

        return {"Time (ms)": current_time_ms, "Hue": round(final_hue, 1), "Sat (%)": round(final_saturation, 1), "V_vec": round(v_vec, 1), "State": state}


# ==========================================
# 2. SINGLE TIME SIGNATURE BOOTSTRAPPER
# ==========================================
class Anchor:
    def __init__(self, measure, beat, time_ms, state_note=""):
        self.measure, self.beat, self.time_ms, self.state_note = measure, beat, time_ms, state_note 
    def __repr__(self):
        return f"M{self.measure} B{self.beat} @ {self.time_ms:04d}ms | [{self.state_note}]"

class STSBootstrapper:
    """Single Time Signature Bootstrapper.
    
    Assumes a fixed meter throughout the piece (e.g. 3/4 waltz, 4/4 march).
    No dynamic meter re-detection = dramatically faster processing.
    """
    def __init__(self, regime_frames, keyframes, beats_per_measure=3, initial_tempo=500.0):
        self.frames = regime_frames 
        self.keyframes = keyframes
        self.anchors = []
        self.current_measure, self.current_beat = 1, 1
        self.last_anchor_time = 0.0
        self.max_time = float(self.frames[-1]["Time (ms)"]) if self.frames else 0
        
        # Fixed meter — no dynamic re-detection
        self.beats_per_measure = beats_per_measure
        self.aqntl = initial_tempo

    def run(self):
        if not self.frames: return []

        # --- BOOTSTRAP: Find first spike as seed ---
        first_spike = self._find_next_spike(0)
        if first_spike is None: return []

        self._lock_anchor(first_spike, "Seed Anchor (Downbeat)", update_tempo=False)

        # --- METRICAL LOOP ---
        while True:
            expected_time = self.last_anchor_time + self.aqntl
            if expected_time > self.max_time: break 

            standard_buffer = self.aqntl * 0.20 
            syncopation_buffer = self.aqntl * 0.50 
            
            spike_time = self._find_spike_in_window(expected_time - standard_buffer, expected_time + standard_buffer)

            # A. On-Beat Transition
            if spike_time is not None:
                self._lock_anchor(spike_time, "On-Beat Transition", update_tempo=True)
                continue
                
            # B. Syncopation Trap
            early_spike = self._find_spike_in_window(expected_time - syncopation_buffer, expected_time - standard_buffer)
            if early_spike is not None:
                self._lock_anchor(early_spike, "Syncopated Anticipation", update_tempo=False)
                self.last_anchor_time = expected_time 
                continue

            # C. Dead-reckon forward (held chord or silence)
            self._lock_anchor(expected_time, "Dead-Reckon", update_tempo=False)

        return self.anchors

    def _lock_anchor(self, time_ms, note, update_tempo=True):
        self.anchors.append(Anchor(self.current_measure, self.current_beat, int(time_ms), state_note=note))
        if update_tempo:
            self.aqntl = (self.aqntl * 0.7) + ((time_ms - self.last_anchor_time) * 0.3) 
        self.last_anchor_time = time_ms
        self._advance_grid_by_beats(1)

    def _advance_grid_by_beats(self, num_beats):
        total_beats = (self.current_beat - 1) + num_beats
        self.current_measure += int(total_beats // self.beats_per_measure)
        self.current_beat = int((total_beats % self.beats_per_measure) + 1)

    def _find_spike_in_window(self, start_ms, end_ms):
        for f in self.frames:
            if start_ms <= f["Time (ms)"] <= end_ms and f["State"] == "TRANSITION SPIKE!": return f["Time (ms)"]
        return None

    def _find_next_spike(self, start_ms):
        for f in self.frames:
            if f["Time (ms)"] > start_ms and f["State"] == "TRANSITION SPIKE!": return f["Time (ms)"]
        return None


# ==========================================
# 3. EXECUTION WRAPPER
# ==========================================
def run_full_pipeline(performance_keyframes, initial_tempo=500.0, beats_per_measure=3):
    """Lightweight pipeline: process only at keyframe timestamps, not every 10ms."""
    detector = HarmonicRegimeDetector()
    frames = []

    # KEY OPTIMIZATION: Only process at actual note onset times, not every 10ms
    for time_ms, notes in performance_keyframes:
        frame = detector.process_frame(time_ms, notes)
        frames.append(frame)

    print(f"STS Bootstrapper: Processed {len(frames)} keyframes (vs {performance_keyframes[-1][0] // 10} frames in full scan)")

    bootstrapper = STSBootstrapper(frames, performance_keyframes, beats_per_measure=beats_per_measure, initial_tempo=initial_tempo)
    return bootstrapper.run()
