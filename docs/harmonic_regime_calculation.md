# Harmonic Regime Calculation — ETME Algorithm Reference

The 4D Electro-Thermodynamic Music Engine (ETME) maps harmonic content to HSL color space through two independent systems: a **Harmonic Regime Detector** (state machine) and a **Rolling Chord Color** calculator (per-note color). Both share the same underlying color wheel but operate at different time scales.

---

## 1. The 12-Node Harmonic Color Wheel

Every pitch class is assigned a fixed angle on a 360° circle. The mapping is **not** chromatic — it follows the circle of fifths, placing consonant intervals near each other and dissonant intervals far apart:

| Interval | Semitones | Angle (°) | Character |
|----------|-----------|-----------|-----------|
| 1 (Unison) | 0 | 0° | Root — Red |
| 5 (Perfect Fifth) | 7 | 30° | Near-root consonance |
| 3 (Major Third) | 4 | 60° | Warm consonance |
| 6 (Major Sixth) | 9 | 90° | Bright consonance |
| 2 (Major Second) | 2 | 120° | Moderate tension |
| 7 (Major Seventh) | 11 | 150° | Strong tension |
| ♭2 (Minor Second) | 1 | 180° | Maximum dissonance |
| ♯4 (Tritone) | 6 | 210° | Destabilizing |
| ♭7 (Minor Seventh) | 10 | 240° | Bluesy tension |
| ♭3 (Minor Third) | 3 | 270° | Dark consonance |
| ♭6 (Minor Sixth) | 8 | 300° | Dark, distant |
| 4 (Perfect Fourth) | 5 | 330° | Suspended tension |

> **Design rationale:** Consonant intervals (1, 5, 3) cluster in the 0°–60° range, making stable chords produce a tight, saturated color vector. Dissonant intervals (♭2, ♯4) sit at 180°–210°, pushing the vector in the opposite direction and reducing saturation when mixed with consonances.

---

## 2. Velocity-Weighted Vector Averaging (Core Formula)

Both the regime detector and per-note color use the same vector averaging math. Given a set of active notes, each with an interval name, octave, and MIDI velocity:

### Step 1 — Normalize velocity to weight

$$w_i = \frac{\text{velocity}_i}{127}$$

### Step 2 — Accumulate weighted vectors

Each note contributes a unit vector at its interval's angle, scaled by weight:

$$X = \sum_i w_i \cdot \cos(\theta_i), \quad Y = \sum_i w_i \cdot \sin(\theta_i)$$

Where $\theta_i$ = `INTERVAL_ANGLES[interval]` in radians.

### Step 3 — Weighted average

$$\bar{x} = \frac{X}{W}, \quad \bar{y} = \frac{Y}{W}, \quad W = \sum_i w_i$$

### Step 4 — Extract HSL

| Dimension | Formula | Range |
|-----------|---------|-------|
| **Hue** | $\text{atan2}(\bar{y}, \bar{x})$ converted to degrees, wrapped to [0°, 360°) | 0–360° |
| **Saturation** | $\sqrt{\bar{x}^2 + \bar{y}^2} \times 100$ | 0–100% |
| **Lightness** | Weighted average of per-note lightness from octave (see below) | 0–100% |
| **Tonal Distance** | Degrees from nearest 30° node: $\left\lvert H - \text{round}(H/30) \times 30 \right\rvert$ | 0–15° |

**Lightness per note** (octave-based, only used in per-note rolling color):

$$L_i = 5 + (\text{octave} - 1) \times 15, \quad \text{clamped to } [0, 100]$$

This maps Octave 1 → 5%, Octave 4 → 50%, Octave 7 → 95%.

### Interpretation

- **High saturation** = the chord is tonally coherent (all vectors point in a similar direction)
- **Low saturation** = the chord is ambiguous or maximally dissonant (vectors cancel out)
- **Tonal distance** = microtonal tension — how far the resultant hue sits from the nearest "pure" consonant node

---

## 3. Rolling Chord Color (Per-Note, `export_etme_data.py`)

Each note in the final JSON gets its own color computed via `compute_rolling_color()`. This simulates **acoustic resonance** — a bass note played 2 seconds ago still "rings" and contributes to the harmonic color.

### Parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `half_life_ms` | 2000 ms | Time for a note's energy to decay to 50% |
| Lookback window | `3 × half_life` = 6000 ms | Maximum resonance memory |
| Lookahead | 50 ms | Prevents color tearing from human arpeggiation |

### Decay Formula

For a note struck at time $t_{\text{onset}}$, evaluated at time $t$:

$$\text{age} = \max(0, \; t - t_{\text{onset}})$$

$$\text{decay} = 0.5^{\,\text{age} / \text{half\_life}}$$

$$v_{\text{decayed}} = \lfloor v_{\text{original}} \times \text{decay} \rfloor$$

### Note Inclusion Rules

A note contributes to the color at time $t$ if **either**:

1. **Recently struck:** onset is within `[t - 6000ms, t + 50ms]` **and** decayed velocity > 0
2. **Actively held:** onset is before the lookback window **but** the note hasn't ended yet (`onset + duration ≥ t`). Gets `max(1, decayed_velocity)` to ensure minimum presence.

The collected notes are then fed into the same vector averaging formula from §2.

---

## 4. Harmonic Regime Detector (State Machine, `STS_bootstrapper.py`)

The `HarmonicRegimeDetector` processes **keyframe timestamps** (note onsets), not every tick. It maintains a sliding buffer of recent frames and classifies each into one of four states.

### Parameters (as used in `export_etme_data.py`)

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `buffer_ms` | 300 ms | Sliding window of recent keyframes |
| `debounce_ms` | 150 ms | Minimum time between consecutive spikes |

### Per-Frame Processing

1. **Buffer management:** Append current frame; evict frames older than `buffer_ms`.
2. **Bass tracking:** Identify the lowest note (by octave, then semitone). Track whether the bass voice changed since last frame.
3. **Vector calculation:** Same weighted vector average as §2, computed over **all notes in the buffer** (not just the current frame).
4. **Velocity of the vector (V_vec):** Rate of change of the harmonic centroid:

$$V_{\text{vec}} = \sqrt{(\bar{x}_t - \bar{x}_{t-1})^2 + (\bar{y}_t - \bar{y}_{t-1})^2} \times 100$$

### State Machine

| State | Condition | Meaning |
|-------|-----------|---------|
| **Silence** | No notes in buffer (`W = 0`) | No harmonic content |
| **Undefined / Gray Void** | Saturation < 30% | Ambiguous — vectors canceling out |
| **TRANSITION SPIKE!** | (`V_vec > 25` **or** bass changed) **and** debounce elapsed | Harmonic landscape just shifted |
| **Regime Locked** | Saturation > 70% **and** V_vec < 8 | Stable, pure harmonic regime |
| **Stable** | Default (none of the above) | Normal state, not remarkable |

### Priority Order

The conditions are evaluated in this order:
1. Silence (short-circuit on zero weight)
2. Gray Void (saturation < 30)
3. Transition Spike (V_vec > 25 OR bass change, with debounce)
4. Regime Locked (saturation > 70 AND V_vec < 8)
5. Stable (fallback)

### Regime Consolidation

After all frames are processed, consecutive frames with the same state are merged into **regime blocks** (contiguous time spans). Micro-regimes shorter than 100ms are absorbed into the preceding block to prevent visual flicker.

---

## 5. Phase 2 — Information Density (Voice Separation)

Separate from the harmonic color system, each note is scored for **auditory salience** using:

$$I_d = f \times P \times T \times \Delta p$$

| Factor | Formula | Meaning |
|--------|---------|---------|
| **f** (Frequency) | `max(1.0, pitch / 60.0)` | Higher notes are more audible |
| **P** (Power) | `velocity / 127.0` | Louder notes command more attention |
| **T** (Temperature) | `1000.0 / Δt` (0 if simultaneous) | Faster note succession = hotter |
| **Δp** (Variance) | `abs(pitch_current - pitch_previous)` | Larger leaps = more information |

Notes scoring above the `melody_threshold` (default: 50.0) are tagged as **"Voice 1 (Liquid / Melody)"**; all others as **"Background (Solid / Harmony)"**.

---

## 6. Pipeline Summary

```
MIDI File
  │
  ├─── extract_keyframes() ──▶ HarmonicRegimeDetector ──▶ Regime Blocks + State per frame
  │                               (buffer_ms=300, debounce_ms=150)
  │
  ├─── midi_to_particles() ──▶ InformationDensityScanner ──▶ id_score + voice_tag per note
  │
  └─── For each particle:
         compute_rolling_color(onset, all_particles, half_life=2000ms)
           └──▶ 4D color: {hue, sat, lightness, tonal_distance}
         closest regime frame
           └──▶ regime_state: Spike / Locked / Stable / etc.
                ▼
         Final JSON per note:
           pitch, velocity, onset, duration,
           hue, sat, lightness, tonal_distance,
           id_score, voice_tag, regime_state
```

---

## 7. Formula Accuracy Notes

After auditing the source code against this document:

- ✅ **INTERVAL_ANGLES** — All 12 angles verified against `STS_bootstrapper.py` L7–10
- ✅ **Vector averaging** — Both `calculate_weighted_chord_color()` and `HarmonicRegimeDetector.process_frame()` use identical math: velocity/127 weighting, cos/sin accumulation, atan2 + magnitude extraction
- ✅ **Exponential decay** — `0.5^(age/half_life)` correctly implements a 2-second acoustic half-life
- ✅ **Lightness** — `5 + (octave-1) × 15` confirmed; correctly clamped to [0, 100]
- ✅ **Tonal distance** — `|H - round(H/30) × 30|` is correct for measuring deviation from nearest 30° node
- ✅ **V_vec** — Euclidean distance between consecutive centroid positions, ×100 for readability
- ✅ **State thresholds** — Saturation < 30 (Gray), V_vec > 25 (Spike), Saturation > 70 + V_vec < 8 (Locked) all match source
- ✅ **Consolidation** — Micro-regimes < 100ms absorbed into predecessor

> [!NOTE]
> The regime detector in `export_etme_data.py` is instantiated with **`buffer_ms=300, debounce_ms=150`** — shorter than the defaults in `STS_bootstrapper.py` (`buffer_ms=2000, debounce_ms=400`). This makes it more responsive for real-time visualization but more trigger-happy for spike detection.
