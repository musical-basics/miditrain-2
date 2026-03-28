"""
Phase 2: Thermodynamic VoiceThreader
Polyphonic voice separation via thermodynamic pathfinding.

Uses Phase 1's Harmonic Regime data (Transition Spikes) as Macro-Gravity
to anchor structural notes into outer bounding voices.
"""
import math


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

        self.LEGATO_GRACE_MS = 40     # Allow 40ms of overlap for human legato

    def _calculate_connection_cost(self, p, thread, is_structural):
        """Calculates the energy (ΔE) required to append particle 'p' to 'thread'."""

        # Base case: Empty thread initialization
        if thread.last_pitch is None:
            # Voice 1 prefers high pitches, Voice 4 prefers low pitches
            # ideal_pitch is set dynamically from the actual pitch range
            base_cost = abs(p.pitch - thread.ideal_pitch) * 0.5

            # Structural notes get a massive discount for waking up outer bounding wires
            if is_structural and (thread.voice_id == 0 or thread.voice_id == self.max_voices - 1):
                base_cost += self.W_GRAVITY
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

        # Dynamically calibrate ideal_pitch from actual pitch range
        if sorted_particles:
            pitch_min = min(p.pitch for p in sorted_particles)
            pitch_max = max(p.pitch for p in sorted_particles)
            pitch_range = max(pitch_max - pitch_min, 12)  # At least one octave
            for t in threads:
                # V0 targets top of range, V(N-1) targets bottom
                t.ideal_pitch = pitch_max - (t.voice_id * (pitch_range / max(1, self.max_voices - 1)))

        for p in sorted_particles:
            # Ask Phase 1: Does this note occur on a Regime Spike?
            is_structural = self._is_phase1_anchor(p, regime_frames)

            best_thread = None
            lowest_cost = float('inf')

            for thread in threads:
                cost = self._calculate_connection_cost(p, thread, is_structural)
                if cost < lowest_cost:
                    lowest_cost = cost
                    best_thread = thread

            if best_thread:
                # Execute the assignment
                if best_thread.last_pitch is not None:
                    best_thread.momentum = math.copysign(1.0, p.pitch - best_thread.last_pitch) if p.pitch != best_thread.last_pitch else 0.0

                best_thread.particles.append(p)
                best_thread.last_pitch = p.pitch
                best_thread.last_end_time = p.onset + p.duration
                p.voice_tag = f"Voice {best_thread.voice_id + 1}"
            else:
                # Polyphony Overload (e.g. a 5-note chord on 4 wires)
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
