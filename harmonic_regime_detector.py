import math

# ==========================================
# HARMONIC REGIME DETECTOR V2.2 — Anchor Isolation
# ==========================================
# Key innovation: the regime's "anchor" (establishing chord) is isolated
# from passing notes. Merged notes contribute to the regime's final color
# but CANNOT drift the anchor centroid. This prevents Centroid Drift.

INTERVAL_ANGLES = {
    "1": 0, "b2": 180, "2": 120, "b3": 270, "3": 60, "4": 330,
    "#4": 210, "5": 30, "b6": 300, "6": 90, "b7": 240, "7": 150
}
SEMITONE_MAP = {
    "1": 0, "b2": 1, "2": 2, "b3": 3, "3": 4, "4": 5,
    "#4": 6, "5": 7, "b6": 8, "6": 9, "b7": 10, "7": 11
}


class HarmonicRegimeDetector:
    """Regime detector with Anchor Isolation and Limbo buffer.

    The establishing chord is locked as an immovable anchor. Passing notes
    merge into the regime block (for final color) but cannot pollute the
    anchor's centroid vector, preventing Centroid Drift.

    Args:
        break_angle:    Minimum angular divergence (degrees) to trigger a
                        regime break. Lowered to 20° for tight progressions.
        min_break_mass: Minimum accumulated mass in the pending group.
        merge_angle:    Maximum angular divergence for harmonically compatible merge.
    """

    # Tuned for sharp regime transitions while isolating the anchor
    def __init__(self, break_angle=40.0, min_break_mass=0.8, merge_angle=25.0):
        self.break_angle = break_angle
        self.min_break_mass = min_break_mass
        self.merge_angle = merge_angle

    # ------------------------------------------------------------------
    # Vector math helpers
    # ------------------------------------------------------------------
    def _compute_vector(self, particles):
        """Velocity-weighted vector average over a list of particle dicts."""
        x, y, mass = 0.0, 0.0, 0.0
        for p in particles:
            rad = math.radians(p['angle'])
            x += p['mass'] * math.cos(rad)
            y += p['mass'] * math.sin(rad)
            mass += p['mass']
        if mass == 0:
            return 0.0, 0.0, 0.0
        return x / mass, y / mass, mass

    def _get_hue_sat(self, x, y):
        """Convert centroid (x, y) to (hue°, saturation%)."""
        deg = math.degrees(math.atan2(y, x))
        hue = deg if deg >= 0 else deg + 360
        sat = min(math.sqrt(x**2 + y**2) * 100.0, 100.0)
        return hue, sat

    def _angle_diff(self, a1, a2):
        """Shortest angular distance on a 360° circle."""
        diff = abs(a1 - a2) % 360
        return 360 - diff if diff > 180 else diff

    # ------------------------------------------------------------------
    # Main processing — the Limbo state machine with Anchor Isolation
    # ------------------------------------------------------------------
    def process(self, keyframes):
        """Process the full timeline of keyframes and return per-frame assignments.

        Args:
            keyframes: list of (time_ms, [(interval, octave, velocity, duration_ms), ...])

        Returns:
            List of dicts with: Time (ms), Regime_ID, Hue, Sat (%), V_vec, State, debug
        """
        anchor_particles = []      # Pure notes that define the regime's unmoving center
        regime_all_particles = []  # All notes merged into the regime (for pure color output)
        limbo_frames = []
        frame_assignments = {}
        regimes = []
        current_regime_id = 0

        for time_ms, notes in keyframes:
            particles = []
            for n in notes:
                interval, octave, velocity = n[0], n[1], n[2]
                angle = INTERVAL_ANGLES.get(interval, 0)
                base_mass = velocity / 127.0

                # 1. Linear Duration Boost (no squaring — prevents crushing fast chords)
                if len(n) >= 4:
                    dur_boost = max(0.5, min(n[3] / 1000.0, 2.0))
                else:
                    dur_boost = 1.0

                # 2. Tamed Register Boost (0.15 per octave, not 0.5)
                distance_from_center = abs(octave - 4)
                register_boost = 1.0 + (distance_from_center * 0.15)

                mass = base_mass * dur_boost * register_boost

                particles.append({
                    'interval': interval, 'octave': octave, 'angle': angle,
                    'mass': mass, 'time': time_ms
                })

            # --- Bootstrap: first frame seeds the anchor ---
            if not anchor_particles:
                anchor_particles = particles.copy()
                regime_all_particles = particles.copy()
                frame_assignments[time_ms] = {
                    'regime_id': current_regime_id, 'state': 'Regime Locked',
                    'debug': {'diff': 0, 'pmass': 0, 'rmass': 0, 'threshold': self.min_break_mass,
                              'particles': [{'int': p['interval'], 'o': p['octave'], 'm': round(p['mass'], 2)} for p in particles]}
                }
                continue

            # Combine all pending limbo notes with the incoming frame
            combined_limbo = [p for _, lf_parts in limbo_frames for p in lf_parts]
            combined_pending = combined_limbo + particles

            # ANCHOR ISOLATION: centroid is calculated strictly from the establishing chord
            rx, ry, rmass = self._compute_vector(anchor_particles)
            r_angle, r_sat = self._get_hue_sat(rx, ry)

            # Pending group centroid
            px, py, pmass = self._compute_vector(combined_pending)
            p_angle, p_sat = self._get_hue_sat(px, py)

            diff = self._angle_diff(r_angle, p_angle)

            # Build debug info for this frame
            frame_debug = {
                'diff': round(diff, 1), 'pmass': round(pmass, 2), 'rmass': round(rmass, 2),
                'threshold': self.min_break_mass,
                'particles': [{'int': p['interval'], 'o': p['octave'], 'm': round(p['mass'], 2)} for p in particles]
            }

            # ─── CASE 1: REGIME BREAK ───────────────────────────
            if diff > self.break_angle and pmass > self.min_break_mass:
                # Flush all limbo notes into the OLD regime (time ordering)
                for lf_time, lf_parts in limbo_frames:
                    regime_all_particles.extend(lf_parts)
                    if lf_time in frame_assignments:
                        frame_assignments[lf_time]['regime_id'] = current_regime_id
                        frame_assignments[lf_time]['state'] = 'Stable'

                regimes.append(regime_all_particles)
                current_regime_id += 1

                # New regime starts cleanly from JUST the triggering frame
                anchor_particles = particles.copy()
                regime_all_particles = particles.copy()
                limbo_frames = []
                frame_assignments[time_ms] = {
                    'regime_id': current_regime_id, 'state': 'TRANSITION SPIKE!',
                    'debug': frame_debug
                }

            # ─── CASE 2: MERGE (harmonically compatible) ────────
            elif diff <= self.merge_angle:
                for lf_time, lf_parts in limbo_frames:
                    regime_all_particles.extend(lf_parts)
                    if lf_time in frame_assignments:
                        frame_assignments[lf_time]['state'] = 'Stable'

                regime_all_particles.extend(particles)
                # CRITICAL: We do NOT append to anchor_particles! Prevents Centroid Drift.
                frame_assignments[time_ms] = {
                    'regime_id': current_regime_id, 'state': 'Stable',
                    'debug': frame_debug
                }
                limbo_frames = []

            # ─── CASE 3: LIMBO (dissonant but not powerful enough) ──
            else:
                limbo_frames.append((time_ms, particles))
                frame_assignments[time_ms] = {
                    'regime_id': current_regime_id, 'state': 'Undefined / Gray Void',
                    'debug': frame_debug
                }

        # --- Clean up: flush remaining limbo into current regime ---
        if limbo_frames:
            for lf_time, lf_parts in limbo_frames:
                regime_all_particles.extend(lf_parts)
                if lf_time in frame_assignments:
                    frame_assignments[lf_time]['state'] = 'Stable'
        regimes.append(regime_all_particles)

        # --- Compute pure colors for each completed regime block ---
        regime_colors = {}
        for rid, rp in enumerate(regimes):
            rx, ry, _ = self._compute_vector(rp)
            hue, sat = self._get_hue_sat(rx, ry)
            regime_colors[rid] = (hue, sat)

        # --- Build output frames ---
        frames_output = []
        prev_x, prev_y = 0.0, 0.0

        for time_ms, notes in keyframes:
            assign = frame_assignments.get(time_ms)
            if not assign:
                continue
            rid, state = assign['regime_id'], assign['state']
            hue, sat = regime_colors.get(rid, (0.0, 0.0))

            cx = (sat / 100.0) * math.cos(math.radians(hue))
            cy = (sat / 100.0) * math.sin(math.radians(hue))
            v_vec = math.sqrt((cx - prev_x)**2 + (cy - prev_y)**2) * 100.0
            prev_x, prev_y = cx, cy

            frames_output.append({
                "Time (ms)": time_ms, "Regime_ID": rid, "Hue": round(hue, 1),
                "Sat (%)": round(sat, 1), "V_vec": round(v_vec, 1),
                "State": state, "debug": assign.get('debug', {})
            })

        return frames_output
