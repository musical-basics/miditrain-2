"""
Phase 2: Thermodynamic VoiceThreader
Polyphonic voice separation via thermodynamic pathfinding.

Uses Phase 1's Harmonic Regime data (Transition Spikes) as Macro-Gravity
to anchor structural notes into outer bounding voices.
"""
import math
import itertools


class VoiceThread:
    """A continuous horizontal stream of particles (e.g., Soprano, Alto, Tenor, Bass)."""
    def __init__(self, voice_id):
        self.voice_id = voice_id
        self.particles = []
        self.last_pitch = None
        self.last_end_time = -9999
        self.momentum = 0.0  # +1 for ascending trajectory, -1 for descending
        self.ideal_pitch = None  # Set dynamically from actual pitch range


class VoiceThreader:
    """Phase 2: Polyphonic Voice Separation via Thermodynamic Pathfinding."""
    def __init__(self, max_voices=4):
        self.max_voices = max_voices

        # Thermodynamic Tuning Weights
        self.W_ELASTICITY = 1.5       # Cost per semitone of pitch stretch (Δp)
        self.W_TEMPERATURE = 2.0      # Cost per second of silence/cooling (Δt)
        self.W_MOMENTUM_PENALTY = 5.0 # Cost to abruptly reverse trajectory
        self.W_GRAVITY = -15.0        # Discount for aligning with Phase 1 Anchors
        self.W_SPAWN_PENALTY = 20.0   # Cost to initialize an empty thread (prevents fragmentation)

        self.LEGATO_GRACE_MS = 40     # Allow 40ms of overlap for human legato

    def _calculate_connection_cost(self, p, thread, is_structural):
        """Calculates the energy (ΔE) required to append particle 'p' to 'thread'."""

        # Base case: Empty thread initialization
        if thread.last_pitch is None:
            # Voice 1 prefers high pitches, Voice 4 prefers low pitches
            # ideal_pitch is set dynamically from the actual pitch range
            # Add a spawn penalty to encourage reusing existing active threads rather than fragmenting
            base_cost = (abs(p.pitch - thread.ideal_pitch) * 0.5) + self.W_SPAWN_PENALTY

            # Structural notes get a massive discount for waking up outer bounding wires
            if is_structural:
                if thread.voice_id == 0 or thread.voice_id == self.max_voices - 1:
                    base_cost += self.W_GRAVITY
                else:
                    # Penalty for putting heavy structural chords in inner filler voices
                    base_cost += abs(self.W_GRAVITY)
            return max(0.0, base_cost)

        # 1. THE PAULI EXCLUSION PRINCIPLE (Collision)
        # Two particles cannot occupy the same monophonic wire simultaneously.
        if p.onset < (thread.last_end_time - self.LEGATO_GRACE_MS):
            return float('inf')

        # 2. ELASTICITY (Pitch Leaps)
        delta_p = abs(p.pitch - thread.last_pitch)
        cost_elastic = delta_p * self.W_ELASTICITY

        # 3. TEMPERATURE (Time Gaps)
        # Fast notes (hot) are cheap to connect. Long rests (cold) make the wire rigid.
        gap_s = max(0, p.onset - thread.last_end_time) / 1000.0
        cost_temp = gap_s * self.W_TEMPERATURE

        # 4. MOMENTUM (Newton's First Law)
        # Continuing an arpeggio/scale is cheaper than reversing direction.
        cost_momentum = 0.0
        direction = p.pitch - thread.last_pitch
        if (direction > 0 and thread.momentum < 0) or (direction < 0 and thread.momentum > 0):
            cost_momentum = self.W_MOMENTUM_PENALTY

        # 5. PHASE 1 MACRO-GRAVITY
        cost_gravity = 0.0
        if is_structural:
            # Structural notes (Regime Spikes) naturally sink into the outer threads (V1/V4).
            if thread.voice_id == 0 or thread.voice_id == self.max_voices - 1:
                cost_gravity = self.W_GRAVITY
            else:
                # Penalty for putting heavy structural chords in inner filler voices
                cost_gravity = abs(self.W_GRAVITY)

        return max(0.0, cost_elastic + cost_temp + cost_momentum + cost_gravity)

    def thread_particles(self, sorted_particles, regime_frames):
        """Scans left-to-right, threading particles into the path of least resistance."""
        threads = [VoiceThread(i) for i in range(self.max_voices)]

        # Sort by onset ascending, then pitch DESCENDING within same onset
        # This ensures the highest note in a chord reaches V1 first
        sorted_particles = sorted(sorted_particles, key=lambda p: (p.onset, -p.pitch))

        # Dynamically calibrate ideal_pitch from actual pitch range
        if sorted_particles:
            pitch_min = min(p.pitch for p in sorted_particles)
            pitch_max = max(p.pitch for p in sorted_particles)
            pitch_range = max(pitch_max - pitch_min, 12)  # At least one octave
            for t in threads:
                # V0 targets top of range, V(N-1) targets bottom
                t.ideal_pitch = pitch_max - (t.voice_id * (pitch_range / max(1, self.max_voices - 1)))

        # Group particles into onset clusters (within 50ms = chord)
        # Within a chord, assign by pitch rank: highest → lowest available thread
        i = 0
        while i < len(sorted_particles):
            # Collect all notes in this onset cluster
            chord_start = sorted_particles[i].onset
            chord = []
            while i < len(sorted_particles) and sorted_particles[i].onset - chord_start <= 50:
                chord.append(sorted_particles[i])
                i += 1

            # Sort chord by pitch descending (soprano first)
            chord.sort(key=lambda p: -p.pitch)

            if len(chord) == 1:
                # Single note: use normal cost auction
                p = chord[0]
                is_structural = self._is_phase1_anchor(p, regime_frames)
                best_thread = None
                lowest_cost = float('inf')
                for thread in threads:
                    cost = self._calculate_connection_cost(p, thread, is_structural)
                    if cost < lowest_cost:
                        lowest_cost = cost
                        best_thread = thread

                if best_thread:
                    if best_thread.last_pitch is not None:
                        best_thread.momentum = math.copysign(1.0, p.pitch - best_thread.last_pitch) if p.pitch != best_thread.last_pitch else 0.0
                    best_thread.particles.append(p)
                    best_thread.last_pitch = p.pitch
                    best_thread.last_end_time = p.onset + p.duration
                    p.voice_tag = f"Voice {best_thread.voice_id + 1}"
                else:
                    p.voice_tag = "Overflow (Chord)"
            else:
                # Multi-note chord: assign by pitch rank to available threads
                # Find which threads are available (not colliding)
                available_threads = []
                for thread in threads:
                    # CRITICAL: Use chord_start (the earliest onset in the cluster)
                    # Because chords are rolled bottom-up, the highest pitch (chord[0]) is usually
                    # played last, making its onset misleadingly late for Pauli Exclusion!
                    if thread.last_pitch is None or chord_start >= (thread.last_end_time - self.LEGATO_GRACE_MS):
                        available_threads.append(thread)

                # Outside-in assignment order: V1 → V4 → V2 → V3
                # Ensures outer bounding voices (soprano/bass) fill first,
                # so a 2-note chord gets V1 + V4, not V1 + V2.
                available_threads.sort(key=lambda t: t.voice_id)

                # We map the notes in `chord` to `available_threads`.
                # We prioritize structural outer limits: V1 for Soprano, V4 for Bass.
                chord_assignment = [None] * len(chord)
                if available_threads:
                    avail_copy = list(available_threads)
                    
                    # 1. Assign highest note to highest available thread
                    chord_assignment[0] = avail_copy.pop(0)
                    
                    # 2. Assign lowest note to Voice 4 IF Voice 4 is available and it's a true bass note
                    # We dynamically check if it falls within ~1.5 octaves (18 semitones) of the piece's
                    # true lowest pitch (ideal_pitch of V4), gracefully adjusting to any key/range.
                    if avail_copy and len(chord) > 1:
                        if avail_copy[-1].voice_id == self.max_voices - 1:
                            if chord[-1].pitch <= avail_copy[-1].ideal_pitch + 18:
                                chord_assignment[-1] = avail_copy.pop(-1)
                                
                    # 3. Fill remaining notes top-down into remaining threads
                    for ci in range(1, len(chord)):
                        if chord_assignment[ci] is None and avail_copy:
                            chord_assignment[ci] = avail_copy.pop(0)

                for ci, p in enumerate(chord):
                    is_structural = self._is_phase1_anchor(p, regime_frames)

                    best_thread = chord_assignment[ci]
                    if not best_thread:
                        # More notes than available threads: use cost auction on ALL threads
                        best_thread = None
                        lowest_cost = float('inf')
                        for thread in threads:
                            cost = self._calculate_connection_cost(p, thread, is_structural)
                            if cost < lowest_cost:
                                lowest_cost = cost
                                best_thread = thread

                    if best_thread and best_thread.last_pitch is not None and p.onset < (best_thread.last_end_time - self.LEGATO_GRACE_MS):
                        # Collision — mark as overflow
                        p.voice_tag = "Overflow (Chord)"
                        continue

                    if best_thread:
                        if best_thread.last_pitch is not None:
                            best_thread.momentum = math.copysign(1.0, p.pitch - best_thread.last_pitch) if p.pitch != best_thread.last_pitch else 0.0
                        best_thread.particles.append(p)
                        best_thread.last_pitch = p.pitch
                        best_thread.last_end_time = p.onset + p.duration
                        p.voice_tag = f"Voice {best_thread.voice_id + 1}"
                        p.voice_id = best_thread.voice_id
                    else:
                        p.voice_tag = "Overflow (Chord)"

        return sorted_particles

    def _is_phase1_anchor(self, p, regime_frames):
        """Check if this particle's onset aligns with a TRANSITION SPIKE! regime frame.
        
        A particle is considered structural if its onset falls within a regime frame
        that is tagged as a Transition Spike — meaning Phase 1 identified this moment
        as a harmonic regime boundary (a downbeat, modulation, or cadence point).
        """
        if not regime_frames:
            return False

        # Find the closest regime frame to this particle's onset
        closest = min(regime_frames, key=lambda f: abs(f["time"] - p.onset))

        # Must be within 50ms of a spike frame to count as structural
        if abs(closest["time"] - p.onset) <= 50 and closest["state"] == "TRANSITION SPIKE!":
            return True

        return False
