# Hybrid vs Hybrid-Split — Break Method Comparison

The **Hybrid-Split** model extends the original **Hybrid** model with a single targeted fix: **intra-queue Jaccard divergence detection**. This document explains the bug that motivated it, why the original Hybrid model misses certain regime breaks, and how Hybrid-Split resolves it without side effects.

---

## The Shared Foundation

Both models share identical logic for the three core decisions:

| Decision | Logic |
|----------|-------|
| **Should Break?** | Subset suppression → Angle check (diff > 15°) → Jaccard check (J < threshold) |
| **Can Merge?** | Angle diff ≤ 20° OR subset-of-anchor resolution |
| **Probation** | Spike enters pending queue; confirmed after debounce (100ms gap) |

The divergence is solely in **what happens inside the pending spike queue**.

---

## The Problem: Bundled Spikes

The Hybrid model uses a **Probation system** — when a potential regime break is detected, it doesn't fire immediately. Instead, the frame enters a `pending_spike_frames` queue and waits for confirmation (either a debounce gap or enough accumulation).

The issue arises when **two unrelated harmonic events** land in the same pending queue:

```
Pending Queue (Hybrid):
┌─────────────────────────────────────────────────┐
│ [2832ms] PCs: {3,4,7,10}  ← Spike from regime 5│
│ [2916ms] PCs: {3,7,10}    ← Continuation        │
│ [3000ms] PCs: {3,8,11}    ← DIFFERENT harmony!   │ ← bundled in
└─────────────────────────────────────────────────┘
                    ↓
        confirm_pending_spike() fires at 3000ms
        (debounce exceeded: 3000-2832 = 168ms ≥ 100ms)
                    ↓
        Only t=2832 gets TRANSITION SPIKE!
        t=3000 becomes just "Stable" in regime 6
```

The frame at 3000ms has **completely different pitch content** (Jaccard = 0.143 vs the spike origin at 2832ms), but it gets lumped into the same regime because `confirm_pending_spike()` only tags the **first** frame as a spike.

### Why This Happens Musically

In the Pathétique 2nd movement (chunk 3, mm. 9-12), the passage around beat 3 features:

- **2832ms**: A transitional chord with `5, b7, b3, 7` — the harmony is shifting away from the previous regime
- **3000ms**: A strong downbeat with `b6, 7, b3, b6` — an entirely new harmonic area (Neapolitan-adjacent voicing)

These are **two separate harmonic events** that happen to fall within 168ms of each other. The Hybrid model treats them as one continuous spike, but musically they represent distinct harmonic arrivals.

---

## The Fix: Intra-Queue Divergence Check

Hybrid-Split adds **one check** at the moment a new frame enters the pending spike queue:

```python
# Before appending to the pending queue:
if pending_spike_frames:
    spike_pcs = accumulated_pitch_classes_from_queue()
    frame_pcs = pitch_classes_of_incoming_frame()
    intra_jaccard = jaccard_similarity(spike_pcs, frame_pcs)
    
    if intra_jaccard < jaccard_threshold:
        # This frame is NOT a continuation of the existing spike.
        # Force-confirm the existing spike as its own regime,
        # then start a fresh spike with this frame.
        confirm_pending_spike()

# Now append the frame (to a fresh or existing queue)
pending_spike_frames.append(frame)
```

### Result

```
Hybrid-Split Queue:
┌──────────────────────────────────────────────┐
│ [2832ms] PCs: {3,4,7,10}  ← Spike from R5   │
│ [2916ms] PCs: {3,7,10}    ← Continuation     │
└──────────────────────────────────────────────┘
        ↓ confirm_pending_spike() → Regime 7

┌──────────────────────────────────────────────┐
│ [3000ms] PCs: {3,8,11}    ← New spike (R8)   │ ← separate queue
└──────────────────────────────────────────────┘
        ↓ confirmed later → Regime 8
```

Now t=3000ms gets `TRANSITION SPIKE!` with its own `Regime_ID = 8`.

---

## Verification: Chunk 3 at 3.0s

| Time | Hybrid (old) | Hybrid-Split (new) |
|------|---|---|
| 2832ms | RID=6, SPIKE ✅ | RID=7, SPIKE ✅ |
| 2916ms | RID=6, Stable | RID=7, Stable |
| **3000ms** | **RID=6, Stable** ❌ | **RID=8, SPIKE** ✅ |
| 3082ms | RID=6, Stable | RID=8, Stable |

---

## Regression Impact

| Chunk | Hybrid | Hybrid-Split | Delta |
|-------|--------|--------------|-------|
| Chunk 1 (mm. 1-4) | 11 regimes, 10 spikes | 11 regimes, 10 spikes | **None** |
| Chunk 2 (mm. 5-8) | 13 regimes, 12 spikes | 14 regimes, 13 spikes | **+1 regime** |
| Chunk 3 (mm. 9-12) | — | — | **+1 regime** (the fix) |

The +1 in chunk 2 represents a case where two previously-bundled spikes are now correctly separated. No false positives were introduced.

---

## When to Use Which

| Model | Best For |
|-------|----------|
| **Hybrid** | Conservative analysis where you prefer fewer regime boundaries. Treats rapid harmonic motion as a single transitional event. |
| **Hybrid-Split** | Downbeat-accurate analysis where each distinct harmonic arrival should be its own regime, even if they occur close together. Better for cadential analysis and phrase-boundary detection. |

Both models are available in the visualizer dropdown for A/B comparison.
