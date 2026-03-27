# Harmonic Regime Calculation V2 — Limbo State Machine

Replaces the frame-by-frame detector (V1) with a **recursive batch processor** that accumulates conflicting notes in a Limbo buffer, triggers regime breaks when mass exceeds a threshold, and **retroactively re-tags** limbo notes to whichever regime they're closest to.

---

## Why V1 Failed

The V1 detector processed each keyframe independently and classified it on the spot. This caused:

1. **False Bass Trap:** `extract_keyframes` only yielded notes struck at that exact millisecond. A single melody note on beat 2 would appear as the "lowest note," triggering a false `TRANSITION SPIKE!`.
2. **Visual Block Fracturing:** Regime blocks were grouped by consecutive same-`State` strings. Since the vector jumped wildly, the state flapped rapidly, spawning a new visual block for every note (the "purple barcode" problem).

---

## Core Design: 3 Cases

Given a set of incoming notes at time *t*, the detector computes the angular divergence between the **current regime centroid** and the **combined pending group** (all limbo + incoming notes):

| Case | Condition | Action |
|------|-----------|--------|
| **Regime Break** | `diff > break_angle` AND `pmass > min_break_mass` | Finalize old regime, retroactively re-tag limbo, start new regime |
| **Merge** | `diff ≤ merge_angle` | Flush limbo into current regime, merge incoming notes |
| **Limbo** | `merge_angle < diff ≤ break_angle` OR insufficient mass | Hold in buffer, tentatively tagged as current regime |

### Default Thresholds

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `break_angle` | 45° | Minimum angular divergence to consider a regime break |
| `min_break_mass` | 1.2 | Minimum accumulated mass to overpower current regime |
| `merge_angle` | 30° | Maximum divergence for harmonically compatible merge |

---

## Mass Calculation

Each note's mass combines velocity and duration:

$$\text{mass} = \frac{\text{velocity}}{127} \times \text{dur\_factor}$$

Where:

$$\text{dur\_factor} = \text{clamp}\left(\frac{\text{duration\_ms}}{1000}, \; 0.5, \; 2.0\right)$$

A quarter note at 1000ms = 1.0× weight. A half note at 2000ms = 2.0× (capped). A sixteenth note at 250ms = 0.5× (floored). This gives sustained bass notes dramatically more mass than passing tones.

---

## Retroactive Loop-Back (The Key Innovation)

When a regime break triggers, the detector **loops backward** through every frame in the Limbo buffer:

```
For each limbo frame:
    angle to OLD regime centroid → diff_old
    angle to NEW regime centroid → diff_new

    if diff_old ≤ diff_new:
        → Re-tag to OLD regime (e.g., passing tone that matched the old key)
    else:
        → Re-tag to NEW regime as TRANSITION SPIKE!
        (e.g., a note that was actually predicting the new harmony)
```

### Worked Example (Pathétique, m. 1)

```
Beat 1-2: A♭ Major chord (A♭, C, E♭)
          → Seeds Regime 0, vector points at ~315° (A♭ ≈ "b6" territory)

Beat 2+:  C melody note on its own
          → diff = small (C = "3" = 60°, within merge_angle of A♭ chord)
          → MERGED into Regime 0

Beat 3:   Strong D♭ in LH + G + B♭ in RH
          → Combined mass = high velocity × long duration = ~1.5+
          → diff from A♭ regime > 45°
          → REGIME BREAK → Regime 1 established (E♭ dom 7th)
          → Any limbo notes retroactively re-tagged
```

---

## Vector Math (Unchanged from V1)

The 12-node harmonic color wheel and vector averaging formula are identical to V1:

$$\bar{x} = \frac{\sum w_i \cos(\theta_i)}{\sum w_i}, \quad \bar{y} = \frac{\sum w_i \sin(\theta_i)}{\sum w_i}$$

$$\text{Hue} = \text{atan2}(\bar{y}, \bar{x})°, \quad \text{Sat} = \sqrt{\bar{x}^2 + \bar{y}^2} \times 100$$

See [harmonic_regime_calculation.md](./harmonic_regime_calculation.md) §1–2 for the full color wheel table and formula details.

---

## Regime Color Computation

After all frames are processed, the detector computes **pure colors** for each completed regime by vector-averaging **all particles** that were assigned to that regime (including retroactively re-tagged ones). This means the color of Regime 0 may shift slightly after its boundary is finalized, because re-tagged limbo notes are removed from its pool.

---

## V_vec (Centroid Velocity)

For the output frames, V_vec is computed as the Euclidean distance between consecutive regime centroids (using their hue/sat as polar coordinates), ×100:

$$V_{\text{vec}} = \sqrt{(x_t - x_{t-1})^2 + (y_t - y_{t-1})^2} \times 100$$

Where $x = \frac{\text{sat}}{100} \cos(\text{hue})$ and $y = \frac{\text{sat}}{100} \sin(\text{hue})$.

---

## Output Format

Each frame in the output now includes `Regime_ID`:

```json
{
    "Time (ms)": 1500,
    "Regime_ID": 1,
    "Hue": 42.3,
    "Sat (%)": 78.5,
    "V_vec": 12.1,
    "State": "TRANSITION SPIKE!"
}
```

Regime blocks in `export_etme_data.py` are now grouped by `Regime_ID` instead of consecutive `State` strings, which eliminates the visual fracturing problem entirely.

---

## Pipeline Change Summary

| Component | V1 | V2 |
|-----------|----|----|
| Processing | Frame-by-frame (`process_frame()`) | Batch (`process()`) |
| Grouping | Consecutive same-State string | `Regime_ID` integer |
| Weighting | Velocity only | Velocity × Duration |
| Conflict handling | Instant spike/void classification | Limbo buffer with deferred decision |
| Re-tagging | None | Retroactive loop-back on regime break |
| Consolidation | Post-hoc 100ms merge | Not needed (stable Regime_ID grouping) |
| Keyframes | 3-tuple (interval, octave, velocity) | 4-tuple (interval, octave, velocity, duration_ms) |
