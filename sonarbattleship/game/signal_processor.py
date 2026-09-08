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
    """FFT-based bandpass filter:
    1. FFT the signal to get frequency components
    2. Zero out everything outside the given range
    3. IFFT back to time domain
    Returns: (filtered_signal, noise_component, frequency_spectrum)
    """
    N = len(signal)
    low_freq, high_freq = band

    X = np.fft.rfft(signal) #FFT the whole signal to get frequency components
    freqs = np.fft.rfftfreq(N,d=1.0/sample_rate) 

    #Keeping track of the frequencies in range
    mask = np.zeros_like(freqs,dtype=float) 
    in_band = (freqs >= low_freq) & (freqs<=high_freq)
    mask[in_band] = 1.0


    ## smooth edges of the mask to prevent abrupt changes
    taper_width = 5
    band_indices = np.where(in_band)[0]
    if len(band_indices) > 2 * taper_width:
        for i in range(taper_width):
            fade = 0.5 * (1 - np.cos(np.pi*i/taper_width))
            mask[band_indices[i]] = fade
            mask[band_indices[-(i+1)]] = fade

    # Apply the created mask and IFFT back
    X_filtered = X * mask
    filtered_signal = np.fft.irfft(X_filtered,n=N)

    noise_component = signal - filtered_signal # the noise part

    spectrum = np.abs(X)/ N # magnitude spectrum

    return filtered_signal,noise_component,spectrum


def generate_template(signal_type='sonar'):
    """Build the known pulse template for matched filtering.
        This is the "reference copy" of what we transmitted - cross-
        correlating it against the received signal finds the echo
    """
    t = time_axis()

    if signal_type == 'sonar':
        # Sonar template: which is Gaussian ping shape we transmit, centered at t=0.5
        template = gaussian_ping(t,SONAR_FREQ,SONAR_SIGMA,1.0,center=0.5)
    else:
        template = gaussian_ping(t,BOMB_FREQ, BOMB_SIGMA,1.0,center=0.5)
    return template
def matched_filter(filtered_signal, template):
    """Cross corelate the filtered signal with the known template.
        The peak position tells us the time delay (and thus distance).
        The peak height tell us detection confidence.

        Returns:(correlation,peak_index,peak_value,estimated_delay)
    """

    # normalize template to unit energy so peak heights are comparable
    template_norm = template/(np.linalg.norm(template) + 1e-10)

    # cross-correlation - 'same' mode keeps output length = input length
    correlation = np.correlate(filtered_signal,template_norm,mode='same')

    # find the peak
    peak_index = np.argmax(np.abs(correlation))
    peak_value = float(np.abs(correlation[peak_index]))

    # converting sample index to time delay
    # 'same' mode centers the output, so index 0 = -N/2 delay
    center_offset = len(filtered_signal)//2
    delay_samples = peak_index - center_offset
    estimated_delay = delay_samples/SAMPLE_RATE

    return correlation.tolist(), int(peak_index), peak_value, estimated_delay


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

    sonar_mask = (freqs >= SONAR_BAND[0]) & (freqs <= SONAR_BAND[1])
    bomb_mask = (freqs >= BOMB_BAND[0]) & (freqs <= BOMB_BAND[1])

    sonar_energy = float(np.sum(power[sonar_mask]))
    bomb_energy = float(np.sum(power[bomb_mask]))

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
