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
from harmonic_regime_detector import HarmonicRegimeDetector, SEMITONE_MAP, ANGLE_MAPS, INTERVAL_ANGLES_DISSONANCE
from information_density import InformationDensityScanner

# Map MIDI pitch class (0-11) to interval names for the regime detector
PC_TO_INTERVAL = {
    0: "1", 1: "b2", 2: "2", 3: "b3", 4: "3", 5: "4",
    6: "#4", 7: "5", 8: "b6", 9: "6", 10: "b7", 11: "7"
}


def calculate_weighted_chord_color(notes, interval_angles=None):
    """
    Calculates HSL color and tension of a chord using MIDI velocity weighting.
    'notes' is a list of tuples: [("interval", octave, velocity_0_to_127), ...]
    
    Returns dict with Hue, Saturation, Lightness, Tonal Distance.
    """
    if interval_angles is None:
        interval_angles = INTERVAL_ANGLES_DISSONANCE
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
        angle_rad = math.radians(interval_angles[interval])
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


def compute_rolling_color(onset_ms, all_particles, regime_start_ms, interval_angles=None):
    """
    Calculates the weighted chord color using active notes.
    Completely truncates any contributing notes that happened before
    the current regime's start time — no exponential decay.
    This prevents color bleeding across regime boundaries.
    
    Lookahead (50ms) prevents 'color tearing' from human MIDI arpeggiation.
    """
    if interval_angles is None:
        interval_angles = INTERVAL_ANGLES_DISSONANCE
    lookahead = onset_ms + 50
    active_notes = []

    for p in all_particles:
        # HARD TRUNCATE: notes struck before the regime boundary are severed
        if p.onset < regime_start_ms:
            continue

        # Optimization: since particles are sorted, stop when we pass lookahead
        if p.onset > lookahead:
            break

        note_end = p.onset + p.duration

        # Note is actively sounding at the current time
        if p.onset <= lookahead and note_end >= onset_ms:
            interval = PC_TO_INTERVAL[p.pitch % 12]
            octave = p.pitch // 12
            active_notes.append((interval, octave, p.velocity))

    if not active_notes:
        return {"hue": 0.0, "sat": 0.0, "lightness": 0.0, "tonal_distance": 0.0}

    return calculate_weighted_chord_color(active_notes, interval_angles)


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


def extract_keyframes(midi_path, group_window_ms=50):
    """Convert MIDI into keyframes for the HarmonicRegimeDetector.
    Groups arpeggiated/rolled notes within `group_window_ms` into a single block.
    Returns list of (time_ms, [(interval_name, octave, velocity, duration_ms), ...])
    """
    score = Score(midi_path)
    tpq = score.ticks_per_quarter
    tick_to_ms = 500.0 / tpq

    raw_notes = []
    for track in score.tracks:
        for note in track.notes:
            time_ms = int(note.start * tick_to_ms)
            interval = PC_TO_INTERVAL[note.pitch % 12]
            octave = note.pitch // 12
            duration_ms = int(note.duration * tick_to_ms)
            raw_notes.append((time_ms, interval, octave, note.velocity, duration_ms))

    raw_notes.sort(key=lambda x: x[0])

    keyframes = []
    current_group_time = None
    current_group_notes = []

    for note in raw_notes:
        time_ms = note[0]
        note_data = (note[1], note[2], note[3], note[4])

        if current_group_time is None:
            current_group_time = time_ms
            current_group_notes.append(note_data)
        elif time_ms - current_group_time <= group_window_ms:
            current_group_notes.append(note_data)
        else:
            keyframes.append((current_group_time, current_group_notes))
            current_group_time = time_ms
            current_group_notes = [note_data]

    if current_group_time is not None:
        keyframes.append((current_group_time, current_group_notes))

    return keyframes


def export_analysis(midi_path, output_json="etme_analysis.json", angle_map='dissonance', break_method='centroid'):
    print(f"Loading MIDI: {midi_path}")
    print(f"  Angle map: {angle_map}, Break method: {break_method}")
    particles = midi_to_particles(midi_path)
    keyframes = extract_keyframes(midi_path)
    print(f"  Loaded {len(particles)} particles, {len(keyframes)} keyframes")

    interval_angles = ANGLE_MAPS.get(angle_map, INTERVAL_ANGLES_DISSONANCE)

    # =============================================
    # Phase 1: HarmonicRegimeDetector V2 (Limbo State Machine)
    # =============================================
    print("Running Phase 1: Harmonic Regime Detector (Limbo V2.2)...")
    detector = HarmonicRegimeDetector(
        break_angle=15.0, min_break_mass=0.75, merge_angle=25.0,
        angle_map=angle_map, break_method=break_method
    )

    # Process all frames at once (batch — enables retroactive re-tagging)
    regime_frames = detector.process(keyframes)

    # Build contiguous regime blocks — split at SPIKE boundaries
    # even within the same regime_id, so spikes are always visible.
    regimes = []
    current_regime = None
    for frame in regime_frames:
        rid = frame["Regime_ID"]
        state = frame["State"]

        # Start a new visual block if:
        # 1. New regime_id, OR
        # 2. State transition: non-SPIKE → SPIKE or SPIKE → non-SPIKE
        is_new_regime = (current_regime is None or current_regime.get("id") != rid)
        is_spike_start = (state == "TRANSITION SPIKE!" and current_regime is not None
                          and current_regime.get("state") != "TRANSITION SPIKE!")
        is_spike_end = (state != "TRANSITION SPIKE!" and current_regime is not None
                        and current_regime.get("state") == "TRANSITION SPIKE!")

        if is_new_regime or is_spike_start or is_spike_end:
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
            # Update within the same visual block
            current_regime["end_time"] = frame["Time (ms)"]
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
            "state": frame["State"],
            "debug": frame.get("debug", {})
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
    print("Computing per-note chord colors (truncating past regimes)...")
    notes_json = []

    # Pre-calculate a fast lookup for regime start times
    def get_regime_start(onset):
        """Find the true start of the regime containing this onset.
        Traces back through any preceding SPIKE blocks with the same
        regime id, since the SPIKE marks the beginning of the regime.
        """
        for i, r in enumerate(regimes):
            if onset >= r["start_time"] and (i == len(regimes) - 1 or onset < regimes[i + 1]["start_time"]):
                # Found the block — now trace back through same-id blocks
                start = r["start_time"]
                rid = r["id"]
                j = i - 1
                while j >= 0 and regimes[j]["id"] == rid:
                    start = regimes[j]["start_time"]
                    j -= 1
                return start
        return regimes[0]["start_time"] if regimes else 0

    for p in scored_particles:
        regime_start = get_regime_start(p.onset)

        # Hard truncate old resonance at regime boundary
        color = compute_rolling_color(p.onset, particles, regime_start, interval_angles)

        # Regime state from detector (for state-based styling like Spike/Locked)
        closest_frame = min(frame_lookup, key=lambda f: abs(f["time"] - p.onset))

        notes_json.append({
            "pitch": p.pitch,
            "velocity": p.velocity,
            "onset": p.onset,
            "duration": p.duration,
            "id_score": round(p.id_score, 2),
            "voice_tag": p.voice_tag,
            # 4D chord color (hard-truncated at regime boundary)
            "hue": color["hue"],
            "sat": color["sat"],
            "lightness": color["lightness"],
            "tonal_distance": color["tonal_distance"],
            # Regime state for styling
            "regime_state": closest_frame["state"],
            # Debug: per-note mass contribution
            "debug": closest_frame.get("debug", {})
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
    midi = "pathetique_test_chunk2.mid"
    sep = "\n" + "="*50 + "\n"

    export_analysis(midi, output_json="etme_analysis.json", break_method='centroid')
    print(sep)
    export_analysis(midi, output_json="etme_analysis_histogram.json", break_method='histogram')
    print(sep)
    export_analysis(midi, output_json="etme_analysis_hybrid.json", break_method='hybrid')
