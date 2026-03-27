import math

# ==========================================
# HARMONIC REGIME DETECTOR V2 — Limbo State Machine
# ==========================================
# Replaces the frame-by-frame detector with a recursive approach:
#   1. Notes that agree with the current regime are merged in.
#   2. Conflicting notes are held in a "Limbo Buffer".
#   3. When limbo mass exceeds the break threshold, a new regime is
#      established and limbo notes are retroactively re-tagged to
#      whichever regime they're closest to.

INTERVAL_ANGLES = {
    "1": 0, "b2": 180, "2": 120, "b3": 270, "3": 60, "4": 330,
    "#4": 210, "5": 30, "b6": 300, "6": 90, "b7": 240, "7": 150
}
SEMITONE_MAP = {
    "1": 0, "b2": 1, "2": 2, "b3": 3, "3": 4, "4": 5,
    "#4": 6, "5": 7, "b6": 8, "6": 9, "b7": 10, "7": 11
}


class HarmonicRegimeDetector:
    """Recursive regime detector with Limbo buffer and retroactive re-tagging.
    
    Args:
        break_angle:    Minimum angular divergence (degrees) between the pending
                        notes and the current regime to trigger a regime break.
        break_ratio:    Incoming pending mass must exceed the current regime's
                        recent mass × this ratio to trigger a break. Prevents
                        single passing tones from overthrowing full chords.
        merge_angle:    Maximum angular divergence (degrees) for a frame to be
                        considered harmonically compatible and merged directly.
        memory_ms:      Hard truncation window (ms). When comparing against
                        incoming notes, only regime particles within the last
                        memory_ms are considered. Everything older is ignored.
    """

    def __init__(self, break_angle=45.0, break_ratio=0.5, merge_angle=30.0, memory_ms=1500.0):
        self.break_angle = break_angle
        self.break_ratio = break_ratio
        self.merge_angle = merge_angle
        self.memory_ms = memory_ms

    # ------------------------------------------------------------------
    # Vector math helpers
    # ------------------------------------------------------------------
    def _compute_vector(self, particles):
        """Velocity-weighted vector average over a list of particle dicts (no decay)."""
        x, y, mass = 0.0, 0.0, 0.0
        for p in particles:
            rad = math.radians(p['angle'])
            x += p['mass'] * math.cos(rad)
            y += p['mass'] * math.sin(rad)
            mass += p['mass']
        if mass == 0:
            return 0.0, 0.0, 0.0
        return x / mass, y / mass, mass

    def _compute_vector_recent(self, particles, reference_time_ms):
        """Like _compute_vector, but hard-truncates: only particles within
        the last memory_ms contribute. Everything older is completely ignored.
        """
        cutoff = reference_time_ms - self.memory_ms
        x, y, mass = 0.0, 0.0, 0.0
        for p in particles:
            if p['time'] < cutoff:
                continue
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
    # Main processing — the Limbo state machine
    # ------------------------------------------------------------------
    def process(self, keyframes):
        """Process the full timeline of keyframes and return per-frame assignments.

        Args:
            keyframes: list of (time_ms, [(interval, octave, velocity, duration_ms), ...])
                       Duration is optional (3-tuple also accepted).

        Returns:
            List of dicts with: Time (ms), Regime_ID, Hue, Sat (%), V_vec, State
        """
        current_regime_particles = []
        limbo_frames = []          # [(time_ms, [particle_dicts])]
        frame_assignments = {}     # time_ms → {regime_id, state}
        regimes = []               # list of particle lists, one per completed regime
        current_regime_id = 0

        for time_ms, notes in keyframes:
            # Convert raw notes to particle dicts with mass
            particles = []
            for n in notes:
                interval = n[0]
                velocity = n[2]
                angle = INTERVAL_ANGLES.get(interval, 0)

                # Incorporate duration weighting if a 4th element is present
                if len(n) >= 4:
                    dur_factor = max(0.5, min(n[3] / 1000.0, 2.0))
                    mass = (velocity / 127.0) * dur_factor
                else:
                    mass = velocity / 127.0

                particles.append({
                    'interval': interval,
                    'angle': angle,
                    'mass': mass,
                    'time': time_ms
                })

            # --- Bootstrap: first frame seeds the initial regime ---
            if not current_regime_particles:
                current_regime_particles.extend(particles)
                frame_assignments[time_ms] = {
                    'regime_id': current_regime_id,
                    'state': 'Regime Locked',
                    'debug': {'diff': 0, 'pmass': 0, 'rmass': 0, 'threshold': 0,
                              'particles': [{'interval': p['interval'], 'mass': round(p['mass'], 3), 'angle': p['angle']} for p in particles]}
                }
                continue

            # Combine all pending limbo notes with the incoming frame
            combined_limbo = [p for _, lf_parts in limbo_frames for p in lf_parts]
            combined_pending = combined_limbo + particles

            # Current regime centroid (TRUNCATED — only recent notes count)
            rx, ry, rmass = self._compute_vector_recent(current_regime_particles, time_ms)
            r_angle, r_sat = self._get_hue_sat(rx, ry)

            # Pending group centroid
            px, py, pmass = self._compute_vector(combined_pending)
            p_angle, p_sat = self._get_hue_sat(px, py)

            diff = self._angle_diff(r_angle, p_angle)

            # Build debug info for this frame
            frame_debug = {
                'diff': round(diff, 1),
                'pmass': round(pmass, 3),
                'rmass': round(rmass, 3),
                'threshold': round(rmass * self.break_ratio, 3),
                'particles': [{'interval': p['interval'], 'mass': round(p['mass'], 3), 'angle': p['angle']} for p in particles]
            }

            # ─── CASE 1: REGIME BREAK ───────────────────────────
            # Pending mass must exceed the regime's recent mass × ratio
            # AND be angularly divergent enough.
            if diff > self.break_angle and pmass > rmass * self.break_ratio:
                regimes.append(current_regime_particles)
                current_regime_id += 1

                # Compute the pure angle of JUST the triggering frame
                fx, fy, fmass = self._compute_vector(particles)
                f_angle, _ = self._get_hue_sat(fx, fy) if fmass > 0 else (p_angle, 0)

                new_regime_particles = []

                # ── RETROACTIVE LOOP-BACK ──
                # Re-evaluate each limbo frame: does it belong to the
                # old regime or the new one?
                for lf_time, lf_parts in limbo_frames:
                    lx, ly, _ = self._compute_vector(lf_parts)
                    l_angle, _ = self._get_hue_sat(lx, ly)
                    diff_old = self._angle_diff(l_angle, r_angle)
                    diff_new = self._angle_diff(l_angle, f_angle)

                    if diff_old <= diff_new:
                        # Closer to old regime — stays tagged there
                        current_regime_particles.extend(lf_parts)
                        frame_assignments[lf_time] = {
                            'regime_id': current_regime_id - 1,
                            'state': 'Stable'
                        }
                    else:
                        # Closer to new regime — retroactively re-tagged!
                        new_regime_particles.extend(lf_parts)
                        frame_assignments[lf_time] = {
                            'regime_id': current_regime_id,
                            'state': 'TRANSITION SPIKE!'
                        }

                new_regime_particles.extend(particles)
                current_regime_particles = new_regime_particles
                limbo_frames = []
                frame_assignments[time_ms] = {
                    'regime_id': current_regime_id,
                    'state': 'TRANSITION SPIKE!',
                    'debug': frame_debug
                }

            # ─── CASE 2: MERGE (harmonically compatible) ────────
            elif diff <= self.merge_angle:
                for lf_time, lf_parts in limbo_frames:
                    current_regime_particles.extend(lf_parts)
                    frame_assignments[lf_time] = {
                        'regime_id': current_regime_id,
                        'state': 'Stable'
                    }
                current_regime_particles.extend(particles)
                frame_assignments[time_ms] = {
                    'regime_id': current_regime_id,
                    'state': 'Stable',
                    'debug': frame_debug
                }
                limbo_frames = []

            # ─── CASE 3: LIMBO (dissonant but not powerful enough) ──
            else:
                limbo_frames.append((time_ms, particles))
                frame_assignments[time_ms] = {
                    'regime_id': current_regime_id,
                    'state': 'Undefined / Gray Void',
                    'debug': frame_debug
                }

        # --- Clean up: flush remaining limbo into current regime ---
        if limbo_frames:
            for lf_time, lf_parts in limbo_frames:
                current_regime_particles.extend(lf_parts)
                frame_assignments[lf_time] = {
                    'regime_id': current_regime_id,
                    'state': 'Stable'
                }
        regimes.append(current_regime_particles)

        # --- Compute pure colors for each completed regime block ---
        regime_colors = {}
        for rid, rp in enumerate(regimes):
            rx, ry, _ = self._compute_vector(rp)
            hue, sat = self._get_hue_sat(rx, ry)
            regime_colors[rid] = (hue, sat)

        # --- Build output frames with V_vec (velocity of the harmonic centroid) ---
        frames_output = []
        prev_x, prev_y = 0.0, 0.0

        for time_ms, notes in keyframes:
            assign = frame_assignments[time_ms]
            rid, state = assign['regime_id'], assign['state']
            hue, sat = regime_colors.get(rid, (0.0, 0.0))

            cx = (sat / 100.0) * math.cos(math.radians(hue))
            cy = (sat / 100.0) * math.sin(math.radians(hue))
            v_vec = math.sqrt((cx - prev_x)**2 + (cy - prev_y)**2) * 100.0
            prev_x, prev_y = cx, cy

            frames_output.append({
                "Time (ms)": time_ms,
                "Regime_ID": rid,
                "Hue": round(hue, 1),
                "Sat (%)": round(sat, 1),
                "V_vec": round(v_vec, 1),
                "State": state,
                "debug": assign.get('debug', {})
            })

        return frames_output
