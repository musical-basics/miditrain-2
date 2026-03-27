import math
from collections import deque

# ==========================================
# HARMONIC REGIME DETECTOR (Physics Engine)
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
