"""
Exports ETME Phase 1 + Phase 2 analysis of a real MIDI file as JSON
for the browser-based piano roll visualizer.

Phase 1 uses the HarmonicRegimeDetector from STS_bootstrapper.py 
(vector-based color wheel with HSL output).
"""
import json
import math
from symusic import Score
from particle import Particle
from harmonic_regime_detector import HarmonicRegimeDetector, SEMITONE_MAP, INTERVAL_ANGLES
from information_density import InformationDensityScanner

# Map MIDI pitch class (0-11) to interval names for the regime detector
PC_TO_INTERVAL = {
    0: "1", 1: "b2", 2: "2", 3: "b3", 4: "3", 5: "4",
    6: "#4", 7: "5", 8: "b6", 9: "6", 10: "b7", 11: "7"
}


def calculate_weighted_chord_color(notes):
    """
    Calculates HSL color and tension of a chord using MIDI velocity weighting.
    'notes' is a list of tuples: [("interval", octave, velocity_0_to_127), ...]
    
    Returns dict with Hue, Saturation, Lightness, Tonal Distance.
    """
    x_total = 0.0
    y_total = 0.0
    lightness_weighted_total = 0.0
    weight_total = 0.0

    for interval, octave, velocity in notes:
        if velocity <= 0:
            continue

        # Normalize MIDI velocity (0-127) to weight (0.0 - 1.0)
        weight = velocity / 127.0
        weight_total += weight

        # Vector coordinates (Hue & Saturation)
        angle_rad = math.radians(INTERVAL_ANGLES[interval])
        x_total += weight * math.cos(angle_rad)
        y_total += weight * math.sin(angle_rad)

        # Lightness from octave (Octave 1 = 5%, Octave 4 = 50%)
        note_lightness = 5.0 + ((octave - 1) * 15.0)
        note_lightness = max(0.0, min(100.0, note_lightness))
        lightness_weighted_total += weight * note_lightness

    if weight_total == 0:
        return {"hue": 0.0, "sat": 0.0, "lightness": 0.0, "tonal_distance": 0.0}

    x_avg = x_total / weight_total
    y_avg = y_total / weight_total

    final_hue = math.degrees(math.atan2(y_avg, x_avg))
    if final_hue < 0:
        final_hue += 360

    final_saturation = math.sqrt(x_avg**2 + y_avg**2) * 100.0
    final_lightness = lightness_weighted_total / weight_total

    # Tonal distance: microtonal tension off nearest 30° node
    nearest_node = round(final_hue / 30.0) * 30.0
    tonal_distance = abs(final_hue - nearest_node)

    return {
        "hue": round(final_hue, 1),
        "sat": round(final_saturation, 1),
        "lightness": round(final_lightness, 1),
        "tonal_distance": round(tonal_distance, 1)
    }


def compute_rolling_color(onset_ms, all_particles, half_life_ms=2000):
    """
    Gathers all notes active near 'onset_ms' and calculates
    the weighted chord color using Acoustic Exponential Decay.
    A bass note played 2 seconds ago will still have 50% of its
    original energy, allowing it to bind an entire measure together.
    Lookahead (50ms) prevents 'color tearing' from human MIDI arpeggiation.
    """
    # Look back 3 half-lives (e.g. 6 seconds) to catch all ringing resonance
    window_start = onset_ms - (half_life_ms * 3)
    lookahead = onset_ms + 50
    active_notes = []

    for p in all_particles:
        note_end = p.onset + p.duration
        
        # Scenario A: Note was struck recently (within our 6s resonance window)
        if p.onset <= lookahead and p.onset >= window_start:
            age = max(0, onset_ms - p.onset)
            # Exponential decay: 0.5 ** (age / half_life)
            decay_factor = 0.5 ** (age / half_life_ms)
            decayed_velocity = int(p.velocity * decay_factor)
            
            if decayed_velocity > 0:
                interval = PC_TO_INTERVAL[p.pitch % 12]
                octave = p.pitch // 12
                active_notes.append((interval, octave, decayed_velocity))
                
        # Scenario B: Note was struck a long time ago, but is actively held/sustained
        elif p.onset < window_start and note_end >= onset_ms:
            age = max(0, onset_ms - p.onset)
            # Even held notes statically decay over time on a piano
            decay_factor = 0.5 ** (age / half_life_ms)
            decayed_velocity = max(1, int(p.velocity * decay_factor))
            
            interval = PC_TO_INTERVAL[p.pitch % 12]
            octave = p.pitch // 12
            active_notes.append((interval, octave, decayed_velocity))

    if not active_notes:
        return {"hue": 0.0, "sat": 0.0, "lightness": 0.0, "tonal_distance": 0.0}

    return calculate_weighted_chord_color(active_notes)


def midi_to_particles(midi_path):
    """Convert a real MIDI file into Particles."""
    score = Score(midi_path)
    tpq = score.ticks_per_quarter
    tick_to_ms = 500.0 / tpq

    particles = []
    for track in score.tracks:
        for note in track.notes:
            particles.append(Particle(
                pitch=note.pitch,
                velocity=note.velocity,
                onset_ms=int(note.start * tick_to_ms),
                duration_ms=int(note.duration * tick_to_ms)
            ))

    particles.sort(key=lambda p: p.onset)
    return particles


def extract_keyframes(midi_path):
    """Convert MIDI into keyframes for the HarmonicRegimeDetector.
    Returns list of (time_ms, [(interval_name, octave, velocity, duration_ms), ...])
    """
    score = Score(midi_path)
    tpq = score.ticks_per_quarter
    tick_to_ms = 500.0 / tpq

    time_map = {}
    for track in score.tracks:
        for note in track.notes:
            time_ms = int(note.start * tick_to_ms)
            interval = PC_TO_INTERVAL[note.pitch % 12]
            octave = note.pitch // 12
            duration_ms = int(note.duration * tick_to_ms)
            if time_ms not in time_map:
                time_map[time_ms] = []
            time_map[time_ms].append((interval, octave, note.velocity, duration_ms))

    return [(t, time_map[t]) for t in sorted(time_map.keys())]


def export_analysis(midi_path, output_json="etme_analysis.json"):
    print(f"Loading MIDI: {midi_path}")
    particles = midi_to_particles(midi_path)
    keyframes = extract_keyframes(midi_path)
    print(f"  Loaded {len(particles)} particles, {len(keyframes)} keyframes")

    # =============================================
    # Phase 1: HarmonicRegimeDetector V2 (Limbo State Machine)
    # =============================================
    print("Running Phase 1: Harmonic Regime Detector (Limbo V2)...")
    detector = HarmonicRegimeDetector(break_angle=45.0, min_break_mass=0.6, merge_angle=30.0, memory_ms=500.0)

    # Process all frames at once (batch — enables retroactive re-tagging)
    regime_frames = detector.process(keyframes)

    # Build contiguous regime blocks using Regime_ID (not State string)
    regimes = []
    current_regime = None
    for frame in regime_frames:
        rid = frame["Regime_ID"]
        state = frame["State"]
        if current_regime is None or current_regime.get("id") != rid:
            if current_regime:
                current_regime["end_time"] = frame["Time (ms)"]
                regimes.append(current_regime)
            current_regime = {
                "id": rid,
                "start_time": frame["Time (ms)"],
                "end_time": frame["Time (ms)"],
                "state": state,
                "hue": frame["Hue"],
                "saturation": frame["Sat (%)"],
                "v_vec": frame["V_vec"]
            }
        else:
            # Update with latest values within the same regime
            current_regime["end_time"] = frame["Time (ms)"]
            # Prioritize visually stable states if it settles
            if state in ["Stable", "Regime Locked"]:
                current_regime["state"] = state
    if current_regime:
        # Extend last regime to cover the last note
        current_regime["end_time"] = particles[-1].onset + particles[-1].duration
        regimes.append(current_regime)

    print(f"  Detected {len(regimes)} harmonic regimes (after consolidation)")
    state_counts = {}
    for r in regimes:
        state_counts[r["state"]] = state_counts.get(r["state"], 0) + 1
    for s, c in state_counts.items():
        print(f"    {s}: {c}")

    # Store per-frame data for regime state lookup
    frame_lookup = []
    for frame in regime_frames:
        frame_lookup.append({
            "time": frame["Time (ms)"],
            "hue": frame["Hue"],
            "sat": frame["Sat (%)"],
            "v_vec": frame["V_vec"],
            "state": frame["State"]
        })

    # Build onset → keyframe notes lookup for deterministic per-note hue
    keyframe_dict = {}
    for time_ms, notes in keyframes:
        keyframe_dict[time_ms] = notes

    # =============================================
    # Phase 2: Information Density
    # =============================================
    print("Running Phase 2: Information Density...")
    scanner = InformationDensityScanner(melody_threshold=50.0)
    scored_particles = scanner.calculate_id_scores(particles)

    melodies = [p for p in scored_particles if "Voice 1" in p.voice_tag]
    print(f"  Tagged {len(melodies)} melody particles")

    # Build JSON output — each note gets rolling 4D color
    print("Computing per-note rolling chord colors (2.0s half-life)...")
    notes_json = []
    for p in scored_particles:
        # Acoustic resonance: 2000ms exponential half-life
        color = compute_rolling_color(p.onset, particles, half_life_ms=2000)

        # Regime state from detector (for state-based styling like Spike/Locked)
        closest_frame = min(frame_lookup, key=lambda f: abs(f["time"] - p.onset))

        notes_json.append({
            "pitch": p.pitch,
            "velocity": p.velocity,
            "onset": p.onset,
            "duration": p.duration,
            "id_score": round(p.id_score, 2),
            "voice_tag": p.voice_tag,
            # 4D chord color (rolling window)
            "hue": color["hue"],
            "sat": color["sat"],
            "lightness": color["lightness"],
            "tonal_distance": color["tonal_distance"],
            # Regime state for styling
            "regime_state": closest_frame["state"]
        })

    regimes_json = []
    for r in regimes:
        regimes_json.append({
            "start_time": r["start_time"],
            "end_time": r["end_time"],
            "state": r["state"],
            "hue": r["hue"],
            "saturation": r["saturation"],
            "v_vec": r["v_vec"]
        })

    data = {
        "notes": notes_json,
        "regimes": regimes_json,
        "stats": {
            "total_notes": len(notes_json),
            "total_regimes": len(regimes_json),
            "melody_notes": len(melodies),
            "background_notes": len(notes_json) - len(melodies)
        }
    }

    with open(output_json, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\n✅ Analysis exported to: {output_json}")
    return data


if __name__ == "__main__":
    export_analysis("pathetique_2_test.mid")
