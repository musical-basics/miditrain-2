import math

# ==========================================
# HARMONIC REGIME DETECTOR V2.2 — Anchor Isolation
# ==========================================
# Key innovation: the regime's "anchor" (establishing chord) is isolated
# from passing notes. Merged notes contribute to the regime's final color
# but CANNOT drift the anchor centroid. This prevents Centroid Drift.

INTERVAL_ANGLES_DISSONANCE = {
    "1": 0, "b2": 180, "2": 120, "b3": 270, "3": 60, "4": 330,
    "#4": 210, "5": 30, "b6": 300, "6": 90, "b7": 240, "7": 150
}

# Standard Circle of Fifths: each step = perfect 5th (30°)
# C→G→D→A→E→B→F#→Db→Ab→Eb→Bb→F
INTERVAL_ANGLES_FIFTHS = {
    "1": 0, "5": 30, "2": 60, "6": 90, "3": 120, "7": 150,
    "#4": 180, "b2": 210, "b6": 240, "b3": 270, "b7": 300, "4": 330
}

ANGLE_MAPS = {
    'dissonance': INTERVAL_ANGLES_DISSONANCE,
    'fifths': INTERVAL_ANGLES_FIFTHS,
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
                        regime break.
        min_break_mass: Minimum accumulated mass in the pending group.
        merge_angle:    Maximum angular divergence for harmonically compatible merge.
        angle_map:      'dissonance' (default) or 'fifths' (standard circle of 5ths).
        break_method:   'centroid' (angle only), 'histogram' (12-bin cosine),
                        or 'hybrid' (centroid + Jaccard set overlap).
    """

    def __init__(self, break_angle=40.0, min_break_mass=0.8, merge_angle=25.0,
                 angle_map='dissonance', break_method='centroid'):
        self.break_angle = break_angle
        self.min_break_mass = min_break_mass
        self.merge_angle = merge_angle
        self.interval_angles = ANGLE_MAPS.get(angle_map, INTERVAL_ANGLES_DISSONANCE)
        self.break_method = break_method

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

    def _build_pc_histogram(self, particles):
        """Build a 12-bin pitch-class histogram weighted by mass."""
        hist = [0.0] * 12
        for p in particles:
            interval = p.get('interval', '1')
            pc = SEMITONE_MAP.get(interval, 0)
            hist[pc] += p['mass']
        return hist

    def _cosine_similarity(self, h1, h2):
        """Cosine similarity between two histograms."""
        dot = sum(a * b for a, b in zip(h1, h2))
        mag1 = math.sqrt(sum(a**2 for a in h1))
        mag2 = math.sqrt(sum(a**2 for a in h2))
        if mag1 == 0 or mag2 == 0:
            return 0.0
        return dot / (mag1 * mag2)

    def _jaccard_similarity(self, particles_a, particles_b):
        """Jaccard similarity of pitch-class sets (ignoring mass)."""
        set_a = {SEMITONE_MAP.get(p['interval'], 0) for p in particles_a}
        set_b = {SEMITONE_MAP.get(p['interval'], 0) for p in particles_b}
        if not set_a and not set_b:
            return 1.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def _should_break(self, anchor_particles, combined_pending, diff, pmass):
        """Determine if a regime break should occur based on the chosen method."""
        if pmass <= self.min_break_mass:
            return False

        if self.break_method == 'centroid':
            return diff > self.break_angle

        elif self.break_method == 'histogram':
            h_anchor = self._build_pc_histogram(anchor_particles)
            h_pending = self._build_pc_histogram(combined_pending)
            cosine_sim = self._cosine_similarity(h_anchor, h_pending)
            # Break if cosine similarity < 0.7 (very different pitch-class content)
            return cosine_sim < 0.7

        elif self.break_method == 'hybrid':
            # Either centroid angle OR Jaccard set difference triggers a break
            if diff > self.break_angle:
                return True
            jaccard = self._jaccard_similarity(anchor_particles, combined_pending)
            # Break if fewer than 50% pitch classes overlap
            return jaccard < 0.5

        return diff > self.break_angle  # fallback

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
                angle = self.interval_angles.get(interval, 0)
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
            if self._should_break(anchor_particles, combined_pending, diff, pmass):
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
