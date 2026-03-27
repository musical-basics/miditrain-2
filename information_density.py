class InformationDensityScanner:
    """Phase 2: Scores every particle based on how much auditory attention it commands.

    Formula: Id = Frequency * Power * Temperature * Variance
    """
    def __init__(self, melody_threshold=50.0):
        self.melody_threshold = melody_threshold

    def calculate_id_scores(self, sequence_of_particles):
        """
        Scores every particle using the master equation:
        Id = f × P × T × Δp
        """
        if len(sequence_of_particles) < 2:
            return sequence_of_particles

        for i in range(1, len(sequence_of_particles)):
            prev_p = sequence_of_particles[i-1]
            curr_p = sequence_of_particles[i]

            # 1. Frequency (Pitch height multiplier)
            # Normalizing around middle C (MIDI 60)
            f_factor = max(1.0, curr_p.pitch / 60.0) 

            # 2. Power (Velocity/Mass)
            p_factor = curr_p.velocity / 127.0 

            # 3. Temperature (Kinetic speed)
            delta_t = curr_p.onset - prev_p.onset
            # If notes are simultaneous (chord), T is 0 for the inner voices
            t_factor = 1000.0 / delta_t if delta_t > 0 else 0.0

            # 4. Variance (Pitch Delta / Entropy)
            delta_pitch = abs(curr_p.pitch - prev_p.pitch)
            # If delta is 0 (repeated note), variance is 0. 
            # If it moves smoothly (step), variance is optimal. 
            # If it leaps wildly, variance spikes.
            v_factor = float(delta_pitch) 

            # The Master Equation
            curr_p.id_score = f_factor * p_factor * t_factor * v_factor
            
            # Tag the particle based on the physical result
            if curr_p.id_score > self.melody_threshold:
                curr_p.voice_tag = "Voice 1 (Liquid / Melody)"
            else:
                curr_p.voice_tag = "Background (Solid / Harmony)"

        return sequence_of_particles
