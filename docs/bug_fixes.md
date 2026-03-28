# ETME Bug Fix Log

## Bug: Polyphonic Voice Stealing and Cascading Overflows
**Date:** March 27, 2026
**Component:** `voice_threader.py` (Phase 2)

### The Issue
During complex piano textures (e.g., Beethoven's Pathetique Sonata), Voice 3 was incorrectly "stealing" repeating inner notes from Voice 4, causing notes to physically jump colors on the visualizer. Additionally, rolling 5-note arpeggiated chords were causing massive overflow spikes (up to 337 dropped notes in a 500-note chunk) because threads were rigidly locking each other out.

### Failed Fix Attempts
1. **Combinatorial Subset Selection (`itertools.combinations`)**
   - *Hypothesis*: By mathematically testing all combinations of chords into available threads, the lowest cost subset would naturally leave Voice 4 open for the true bass line.
   - *Why it failed*: Rigid `p.onset < thread.last_end_time` logic caused Pauli Exclusion to violently trigger `float('inf')` for any arpeggiated chords that overlapped with sustained pedal notes, creating a bottleneck that dumped 60%+ of the notes into Overflow.
2. **Top-Down Array-Mapping with Hardcoded Middle-C (`< 60` threshold)**
   - *Hypothesis*: Explicitly bounding the highest note to V1 and the lowest note to V4 (if `< 60`) would bypass Pauli Exclusion entirely.
   - *Why it failed*: While it successfully dropped the overflows from 337 back to 65, the user rejected the rigid "Middle-C" rule because it breaks on transposed pieces, and it still allowed V4 to incorrectly snatch low tenor notes before the true bass entered.

### The Final Solution: Soft Pauli Exclusion & Thermodynamic Greedy Auction
- **The Fix**: Replaced the rigid `if/else` threading loops with a robust Thermodynamic Auction powered by "Soft Pauli Exclusion."
- **How it Works**: 
  - Instead of blocking overlapping notes with `float('inf')`, pedal overlaps now pay a soft `cost_collision` penalty. This allows V1, V2, and V3 to comfortably absorb rolling arpeggios even while the sustain pedal is down, without falsely locking out threads.
  - Using `math.log1p(gap_s)` (Logarithmic Cooling) rather than linear cooling prevents long rests from becoming infinitely expensive, allowing resting voices to wake up properly rather than forcing active voices to stretch 20 semitones.
  - A permanent "Register Gravity" was added (`abs(p.pitch - thread.ideal_pitch) * self.W_REGISTER`), constantly pulling Voice 4 back down to the Bass clef if it strays.
- **Result**: The repeating tenor notes visually stabilized, and chunk Overflows plummeted from 337 to 20, gracefully preserving physics-based threading without brittle boolean rules.
