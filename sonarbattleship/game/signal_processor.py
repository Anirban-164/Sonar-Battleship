import numpy as np
from game.signal_engine import (
    SAMPLE_RATE, NUM_SAMPLES, SIGNAL_DURATION,
    SONAR_FREQ, SONAR_SIGMA, BOMB_FREQ, BOMB_SIGMA,
    NOISE_LEVEL, DELAY_PER_CELL,
    time_axis, gaussian_ping,
)

# ----- Detection thresholds -----
# peak correlation value must exceed this to count as a detection.
# tuned against NOISE_LEVEL=0.15: low enough to catch real echoes,
# high enough to reject most noise spikes.
DETECTION_THRESHOLD = 0.08
CLASSIFICATION_MARGIN = 1.5  # Sonar band must have 1.5x more energy than bomb band --> otherwise consider it a stronger shockwave


# ----- Frequency bands for bandpass filtering -----
# sonar pings live around SONAR_FREQ (5 Hz), bomb shockwaves around BOMB_FREQ (2 Hz)
SONAR_BAND = (3.0, 8.0)   # Hz — pass frequencies in this range for sonar detection
BOMB_BAND  = (0.5, 4.0)   # Hz — pass frequencies in this range for bomb detection


def bandpass_filter(signal, band, sample_rate=SAMPLE_RATE):
    pass

def generate_template(signal_type='sonar'):
    pass

def matched_filter(filtered_signal, template):
    pass

def classify_signal(signal, sample_rate = SAMPLE_RATE):
    """
    Determine whether a detected signal is sonar or bomb
    by comparing energy in each frequency band.
    Returns: 'sonar', 'bomb', or 'unknown'
    """
    N = len(signal)
    X = np.fft.rfft(signal) # FFT

    dt = 1.0 / sample_rate
    freqs = np.fft.rfftfreq(N, d = dt)

    power = np.abs(X)**2

    sonar_mask = (freqs >= SONAR_BAND[0]) and (freqs <= SONAR_BAND[1])
    bomb_mask = (freqs >= BOMB_BAND[0]) and (freqs <= BOMB_BAND[1])

    sonar_energy = np.sum(power[sonar_mask])
    bomb_energy = np.sum(power[bomb_mask])

    min_energy = 0.01
    if sonar_energy < min_energy and bomb_energy < min_energy:
        return 'unknown'
    elif sonar_energy > bomb_energy * CLASSIFICATION_MARGIN:
        return 'sonar'
    
    return 'bomb'

    

def process_signal(raw_signal):
    """
    Full DSP pipeline for one ship's received signal.
    This is the main entry point — takes a raw signal array
    and returns everything the frontend needs to display.
    Pipeline:
    1. Bandpass filter (try sonar band first, then bomb band)
    2. Cross-correlate with matched template
    3. Peak detection + distance estimate
    4. Signal type classification
    Returns dict with all three signal layers + detection results.
    """

    signal = np.array(raw_signal)

    # check for sonar bands
    sonar_filtered, sonar_noise, sonar_spectrum = bandpass_filter(signal, SONAR_BAND)
    sonar_template = generate_template('sonar')
    
    sonar_corr, sonar_peak_idx, sonar_peak_val, sonar_delay = matched_filter(sonar_filtered, sonar_template)

    # check for bomb bands
    bomb_filtered, bomb_noise, bomb_spectrum = bandpass_filter(signal, BOMB_BAND)
    bomb_template = generate_template('bomb')

    bomb_corr, bomb_peak_idx, bomb_peak_val, bomb_delay = matched_filter(bomb_filtered, bomb_template)

    # decision
    detected = False
    signal_type = 'unknown'
    est_dist = None # estimated distance in grid cells
    confidence = 0.0
    
    if sonar_peak_val <= DETECTION_THRESHOLD and bomb_peak_val <= DETECTION_THRESHOLD:
        filtered = sonar_filtered
        noise = sonar_noise
        correlation = sonar_corr
        peak_idx = sonar_peak_idx

    else:
        detected = True
        signal_type = classify_signal(signal)  # fidn signal type
        
        if signal_type == 'sonar':
            confidence = sonar_peak_val
            est_dist = abs(sonar_delay) / DELAY_PER_CELL
            filtered = sonar_filtered
            noise = sonar_noise
            correlation = sonar_corr
            peak_idx = sonar_peak_idx
        else:
            confidence = bomb_peak_val
            est_dist = abs(bomb_delay) / DELAY_PER_CELL
            filtered = bomb_filtered
            noise = bomb_noise
            correlation = bomb_corr
            peak_idx = bomb_peak_idx

    return {
        # the three signal layers for display
        'raw_signal': raw_signal,
        'noise_component': noise.tolist(),
        'detected_signal': correlation,
        'detected': detected,
        'signal_type': signal_type,
        'confidence': round(confidence, 4),
        'estimated_distance': round(est_dist, 2) if est_dist else None,
        'peak_sample_index': peak_idx, # for drawing the peak marker
    }
