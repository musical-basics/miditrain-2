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

    def __init__(self, break_angle=40.0, min_break_mass=0.8, merge_angle=20.0,
                 angle_map='dissonance', break_method='centroid', debounce_ms=100):
        self.break_angle = break_angle
        self.min_break_mass = min_break_mass
        self.merge_angle = merge_angle
        self.interval_angles = ANGLE_MAPS.get(angle_map, INTERVAL_ANGLES_DISSONANCE)
        self.break_method = break_method
        self.debounce_ms = debounce_ms

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

    def _get_dominant_pcs(self, particles):
        """Extract set of pitch classes from particles, ignoring trace elements < 20% of max mass."""
        if not particles:
            return set()
        max_m = max(p['mass'] for p in particles)
        threshold = max_m * 0.15
        return {SEMITONE_MAP.get(p['interval'], 0) for p in particles if p['mass'] >= threshold}

    def _jaccard_similarity(self, set_a, set_b):
        """Jaccard similarity of two sets."""
        if not set_a and not set_b:
            return 1.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def _should_break(self, anchor_particles, combined_pending, diff, pmass, is_subset=False, jaccard=1.0):
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
            # 1. Subset Rule: if incoming notes are just a re-voicing/subset of the 
            # established regime, suppress the break (even if angle diff is large due to volume).
            if is_subset:
                return False

            # 2. Angle Rule
            if diff > self.break_angle:
                return True
                
            # 3. Set Divergence Rule
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
        anchor_profile = {}        # {interval: weight} — persistent core of the regime
        regime_all_particles = []  # All notes merged into the regime (for pure color output)
        limbo_frames = []
        pending_spike_frames = []  # Neighbor Tone Limbo (Probation)
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
            if not anchor_profile:
                for p in particles:
                    anchor_profile[p['interval']] = anchor_profile.get(p['interval'], 0) + p['mass']
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

            # ANCHOR ISOLATION: Construct pseudo-particles from the persistent profile
            anchor_particles = [{'interval': i, 'mass': w, 'angle': self.interval_angles.get(i, 0)} for i, w in anchor_profile.items()]
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

            # Check subset rules to evaluate resolutions and suppress false limbos
            is_subset_anchor = False
            is_subset_spike = False
            jaccard = 1.0
            
            if self.break_method in ('hybrid', 'histogram'):
                set_pending = self._get_dominant_pcs(combined_pending)
                set_anchor = self._get_dominant_pcs(anchor_particles)
                is_subset_anchor = bool(set_pending and set_pending.issubset(set_anchor))
                
                if set_pending and set_anchor:
                    jaccard = len(set_pending.intersection(set_anchor)) / len(set_pending.union(set_anchor))
                elif set_pending and not set_anchor:
                    jaccard = 0.0
                
                if pending_spike_frames:
                    # Construct pseudo-particles for the accumulated pending spike
                    spike_pcs = set()
                    for _, ps_parts, _ in pending_spike_frames:
                        spike_pcs.update(self._get_dominant_pcs(ps_parts))
                    is_subset_spike = bool(set_pending and set_pending.issubset(spike_pcs))

            # Ambiguity Resolution: An isolated note (e.g. B) may belong to both the I chord AND the V7 chord.
            # If it belongs to the pending modulation, it continues the tension rather than prematurely resolving it.
            is_resolution = is_subset_anchor and not is_subset_spike
            
            # If the notes clearly belong to the active modulation, do not allow them to merge into the old regime
            # even if their angle difference happens to be < 25.0
            if pending_spike_frames and is_subset_spike:
                can_merge = False
            else:
                can_merge = (diff <= self.merge_angle) or is_resolution

            # ─── CASE 1: REGIME BREAK (OR PENDING SPIKE) ────────
            # Note: _should_break uses is_subset_anchor to suppress initial breaks
            if self._should_break(anchor_particles, combined_pending, diff, pmass, is_subset_anchor, jaccard) or \
               (pending_spike_frames and not can_merge):
                
                # Tension is initiated or continuing
                pending_spike_frames.append((time_ms, particles, frame_debug))
                
                first_spike_time = pending_spike_frames[0][0]
                if time_ms - first_spike_time >= self.debounce_ms:
                    # PROBATION FAILED: CONFIRM SPIKE
                    # 1. Flush limbo frames into OLD regime
                    for lf_time, lf_parts in limbo_frames:
                        regime_all_particles.extend(lf_parts)
                        if lf_time in frame_assignments:
                            frame_assignments[lf_time]['regime_id'] = current_regime_id
                            frame_assignments[lf_time]['state'] = 'Stable'

                    # 2. Finalize OLD regime
                    regimes.append(regime_all_particles)
                    current_regime_id += 1

                    # 3. New regime starts cleanly from the FIRST pending spike
                    first_parts = pending_spike_frames[0][1]
                    anchor_profile = {}
                    for p in first_parts:
                        anchor_profile[p['interval']] = anchor_profile.get(p['interval'], 0) + p['mass']
                    
                    regime_all_particles = []
                    
                    # 4. Flush all pending spikes into NEW regime
                    for ps_time, ps_parts, ps_debug in pending_spike_frames:
                        regime_all_particles.extend(ps_parts)
                        state = 'TRANSITION SPIKE!' if ps_time == first_spike_time else 'Stable'
                        frame_assignments[ps_time] = {
                            'regime_id': current_regime_id, 'state': state,
                            'debug': ps_debug
                        }
                        
                        # Reinforce anchor for subsequent frames in the queue
                        if ps_time != first_spike_time:
                            cur_ints = {p['interval'] for p in ps_parts}
                            for p in ps_parts:
                                i = p['interval']
                                anchor_profile[i] = min(3.0, anchor_profile.get(i, 0) + p['mass'])
                            for i in list(anchor_profile.keys()):
                                if i not in cur_ints:
                                    anchor_profile[i] *= 0.95
                                    if anchor_profile[i] < 0.05:
                                        del anchor_profile[i]
                                        
                    limbo_frames = []
                    pending_spike_frames = []
                else:
                    # PROBATION: Tension has not yet exceeded debounce_ms, wait.
                    frame_assignments[time_ms] = {
                        'regime_id': current_regime_id, 'state': 'Pending Spike',
                        'debug': frame_debug
                    }

            # ─── CASE 2: MERGE (harmonically compatible) ────────
            elif can_merge:
                # RESOLUTION: Swallow any pending spikes back into the regime
                if pending_spike_frames:
                    for ps_time, ps_parts, ps_debug in pending_spike_frames:
                        regime_all_particles.extend(ps_parts)
                        frame_assignments[ps_time] = {
                            'regime_id': current_regime_id, 'state': 'Swallowed Spike',
                            'debug': ps_debug
                        }
                    pending_spike_frames = []
                    
                for lf_time, lf_parts in limbo_frames:
                    regime_all_particles.extend(lf_parts)
                    if lf_time in frame_assignments:
                        frame_assignments[lf_time]['state'] = 'Stable'

                regime_all_particles.extend(particles)
                
                # CRITICAL: Reinforce persistent anchor notes, decay absent ones
                current_intervals = {p['interval'] for p in particles}
                
                # Reinforce present notes
                for p in particles:
                    i = p['interval']
                    if i in anchor_profile:
                        # Reward persistence (cap at 3.0)
                        anchor_profile[i] = min(3.0, anchor_profile[i] + p['mass'])
                    else:
                        # Introduce new voices at their baseline mass
                        anchor_profile[i] = p['mass']
                
                # Decay absent notes
                for i in list(anchor_profile.keys()):
                    if i not in current_intervals:
                        anchor_profile[i] *= 0.95
                        if anchor_profile[i] < 0.05:
                            del anchor_profile[i]

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
        if pending_spike_frames:
            # File ended during a spike probation -> Confirm the spike as the final regime
            first_spike_time = pending_spike_frames[0][0]
            for lf_time, lf_parts in limbo_frames:
                regime_all_particles.extend(lf_parts)
                if lf_time in frame_assignments:
                    frame_assignments[lf_time]['state'] = 'Stable'
            regimes.append(regime_all_particles)
            current_regime_id += 1
            
            regime_all_particles = []
            for ps_time, ps_parts, ps_debug in pending_spike_frames:
                regime_all_particles.extend(ps_parts)
                state = 'TRANSITION SPIKE!' if ps_time == first_spike_time else 'Stable'
                if ps_time in frame_assignments:
                    frame_assignments[ps_time]['regime_id'] = current_regime_id
                    frame_assignments[ps_time]['state'] = state
            regimes.append(regime_all_particles)
        else:
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
