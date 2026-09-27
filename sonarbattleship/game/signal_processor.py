import numpy as np

from game.signal_engine import (
    SAMPLE_RATE, NUM_SAMPLES, SIGNAL_DURATION,
    SONAR_FREQ, SONAR_SIGMA, SONAR_AMPLITUDE, ECHO_GAIN,
    BOMB_FREQ, BOMB_SIGMA, BOMB_AMPLITUDE,
    HULL_FREQ, HULL_SIGMA, HULL_AMPLITUDE, HULL_RING_LAG,
    NOISE_LEVEL, DELAY_PER_CELL, ATTENUATION_ALPHA,
    REFERENCE_SHIP_SIZE, PULSE_ORIGIN_OFFSET,
    time_axis, gaussian_ping, size_pulse_width,
)

# ----- Detection thresholds -----
# The old code compared the raw matched-filter peak against a fixed
# number (0.30). That could never be right for long: the peak height
# depends on how loud the echo was, which depends on distance and on the
# size of the target, so a genuine contact from a small boat far away sat
# below it while a close blast sat far above it. Worse, that same raw
# peak was handed to the UI and multiplied by 100 to make a
# "confidence %", which happily printed numbers well over 100%.
# What matters is how far the peak stands out of the noise around it. We
# measure the noise floor from the correlation trace itself and work in a
# signal-to-noise ratio, which is dimensionless and comparable across
# every event in the game.
SNR_DETECTION_THRESHOLD = 5.5   # peak must be this many times the noise floor
CONFIDENCE_SLOPE = 0.55         # how sharply confidence saturates either side
MIN_PEAK_ABSOLUTE = 0.02        # absolute floor, guards against silent input

# Kept for anything still importing it; the SNR test above is what decides.
DETECTION_THRESHOLD = MIN_PEAK_ABSOLUTE

# Energy ratio a band needs before we believe it over its neighbour.
CLASSIFICATION_MARGIN = 1.5


# ----- Frequency bands for bandpass filtering -----
# These no longer overlap. They used to (sonar 3-8, bomb 0.5-4), so a
# single event showed up in both bands and the classifier was choosing
# between two views of the same energy.
#   bomb blast  ~2 Hz   (broad, low)
#   sonar ping  ~5 Hz   (the transmitted pulse and its echo)
#   hull ring  ~12 Hz   (only exists when a bomb breaks a hull)
BOMB_BAND = (0.5, 3.0)
SONAR_BAND = (3.0, 8.0)
HULL_BAND = (8.0, 17.0)
# Sonar template bank. We do not know how big the thing out there is, so
# we correlate against one template per plausible submarine size and let
# the best match tell us. This is the "use the size of the submarine to
# work out what is on the path" part — a 5-cell boat returns a slightly
# wider echo than a 3-cell boat.
SONAR_SIZE_HYPOTHESES = (3, 4, 5)

# Plausible range for a reported size estimate.
MIN_REPORTED_SIZE = 2
MAX_REPORTED_SIZE = 6

# Nothing can come back before it was sent. Restricting the peak search
# to non-negative delays removes half the opportunities for noise to
# masquerade as a contact, and is simply true.
_MIN_LAG_SAMPLE = int(round(PULSE_ORIGIN_OFFSET * SAMPLE_RATE))


def BandpassFilter(signal, band, sample_rate=SAMPLE_RATE):
    """FFT-based bandpass filter:
    1. FFT the signal to get frequency components
    2. Zero out everything outside the given range
    3. IFFT back to time domain
    Returns: (filtered_signal, noise_component, frequency_spectrum)
    """
    N = len(signal)
    low_freq, high_freq = band
    X = np.fft.rfft(signal)  # FFT the whole signal
    freqs = np.fft.rfftfreq(N, d=1.0 / sample_rate)
    #Extracting the frequencies in range
    mask = np.zeros_like(freqs, dtype=float)
    in_band = (freqs >= low_freq) & (freqs <= high_freq)
    mask[in_band] = 1.0
    #Smooth edges of the mask to nullify abrupt changes
    taper_width = 5
    band_indices = np.where(in_band)[0]
    if len(band_indices) > 2 * taper_width:
        for i in range(taper_width):
            fade = 0.5 * (1 - np.cos(np.pi * i / taper_width))
            mask[band_indices[i]] = fade
            mask[band_indices[-(i + 1)]] = fade
    #Apply the created mask and IFFT
    X_filtered = X * mask
    filtered_signal = np.fft.irfft(X_filtered, n=N)
    noise_component = signal - filtered_signal  #Noise part
    spectrum = np.abs(X) / N  #Magnitude spectrum
    return filtered_signal, noise_component, spectrum


def GenerateTemplate(signal_type='sonar', size=REFERENCE_SHIP_SIZE):
    """
    Full-length reference copy of the pulse we expect, centred at
    PULSE_ORIGIN_OFFSET.
    Kept for plotting and for anything that wants to see the template on
    the same time axis as the signal. The detector itself uses the
    compact quadrature pair below.
    """
    t = time_axis()
    if signal_type == 'sonar':
        return gaussian_ping(t, SONAR_FREQ, size_pulse_width(size), 1.0,
                             center=PULSE_ORIGIN_OFFSET)
    if signal_type == 'hull':
        return gaussian_ping(t, HULL_FREQ, HULL_SIGMA, 1.0,
                             center=PULSE_ORIGIN_OFFSET)
    return gaussian_ping(t, BOMB_FREQ, BOMB_SIGMA, 1.0,
                         center=PULSE_ORIGIN_OFFSET)


def CompactQuadratureTemplate(freq, sigma):
    """
    The pulse cropped to the few hundred milliseconds it actually
    occupies, as a sine or cosine pair.
    There are two reasons:
    1.Length:-->Correlating two 600-sample arrays leaves the ends of the
      output with almost no overlap, so the trace tapers to nearly zero
      at both edges. Any robust noise estimate taken over that trace is
      then dominated by the dead ends and comes out far too low, which
      is what used to make pure ocean noise look like a solid contact.
    2.Phase:-->The echo's carrier phase depends on its arrival time, so a
      fixed-phase template only matches at some delays. Correlating
      against sine AND cosine and taking the magnitude gives the
      envelope, which is phase-independent — the textbook matched filter
      for a pulse of unknown phase.
    """
    half = int(round(4.0 * sigma * SAMPLE_RATE))
    n = 2 * half + 1
    tau = (np.arange(n) - half) / SAMPLE_RATE
    envelope = np.exp(-0.5 * (tau / sigma) ** 2)

    t_sin = envelope * np.sin(2 * np.pi * freq * tau)
    t_cos = envelope * np.cos(2 * np.pi * freq * tau)

    norm = np.linalg.norm(t_sin) + 1e-12
    return t_sin / norm, t_cos / norm, half


def EnvelopeCorrelate(signal, t_sin, t_cos):
    """Quadrature matched filter to phase-independent envelope."""
    cs = np.correlate(signal, t_sin, mode='same')
    cc = np.correlate(signal, t_cos, mode='same')
    return np.sqrt(cs ** 2 + cc ** 2)


class Detector:
    """One hypothesis: a band, a pulse shape, and its calibration."""
    def __init__(self, name, band, freq, sigma, size=None):
        self.name = name
        self.band = band
        self.freq = freq
        self.sigma = sigma
        self.size = size
        self.t_sin, self.t_cos, self.half = CompactQuadratureTemplate(freq, sigma)

        # Calibrate: push a clean, noiseless pulse of amplitude 1.0
        # through the exact same chain and record the peak it produces.
        # Dividing a measured peak by this recovers the arriving
        # amplitude, which is what the size estimate is built on. Doing
        # it by measurement rather than by algebra means the bandpass
        # filter's own loss is automatically accounted for.
        t = time_axis()
        reference = gaussian_ping(t, freq, sigma, 1.0, center=PULSE_ORIGIN_OFFSET)
        filtered, _, _ = BandpassFilter(reference, band)
        env = EnvelopeCorrelate(filtered, self.t_sin, self.t_cos)
        self.unit_peak = float(np.max(env)) or 1.0

    def run(self, signal):
        filtered, _residue, _spectrum = BandpassFilter(signal, self.band)
        # Pad before correlating so that EVERY sample position gets the
        # full template laid over it. Without this the usable lag range
        # starts `half` samples in — and for the broad, low-frequency
        # blast template that is 0.6s, which is past the arrival time of
        # any bomb going off nearby. Close explosions were landing
        # outside the search window and being reported as "nothing".
        pad = self.half
        padded = np.concatenate([np.zeros(pad), filtered, np.zeros(pad)])
        env_full = EnvelopeCorrelate(padded, self.t_sin, self.t_cos)
        env = env_full[pad:pad + len(filtered)]
        n = len(env)
        # Nothing can arrive before it was transmitted, so only search
        # from the zero-delay position onwards.
        lo = max(0, _MIN_LAG_SAMPLE - 3)
        hi = max(lo + 1, n)
        window = env[lo:hi]
        rel_peak = int(np.argmax(window))
        peak_index = lo + rel_peak
        peak_value = float(window[rel_peak])
        # Noise floor: the typical envelope level away from the peak.
        # The median is used rather than the mean so one loud echo cannot
        # inflate the floor it is being measured against.
        guard = max(4, int(round(2.0 * self.sigma * SAMPLE_RATE)))
        mask = np.ones(window.shape, dtype=bool)
        mask[max(0, rel_peak - guard):rel_peak + guard + 1] = False
        background = window[mask] if mask.sum() >= 32 else window
        floor = float(np.median(background))
        if not np.isfinite(floor) or floor < 1e-9:
            floor = 1e-9
        snr = peak_value / floor
        # peak index maps straight onto the pulse's arrival time, so the
        # delay is just that time minus where an undelayed pulse sits.
        arrivalTime = peak_index / SAMPLE_RATE
        delay = arrivalTime - PULSE_ORIGIN_OFFSET

        return {
            'filtered': filtered,
            'correlation': env.tolist(),
            'peak_index': peak_index,
            'peak_value': peak_value,
            'amplitude': peak_value / self.unit_peak,
            'floor': floor,
            'snr': snr,
            'delay': delay,
            'detected': (snr >= SNR_DETECTION_THRESHOLD
                         and peak_value >= MIN_PEAK_ABSOLUTE),
            'confidence': snr_to_confidence(snr),
            'size_hypothesis': self.size,
        }


# Built once at import — the calibration pass is not free.
_SONAR_DETECTORS = [
    Detector(f'sonar{s}', SONAR_BAND, SONAR_FREQ, size_pulse_width(s), size=s)
    for s in SONAR_SIZE_HYPOTHESES
]
_BOMB_DETECTOR = Detector('bomb', BOMB_BAND, BOMB_FREQ, BOMB_SIGMA)
_HULL_DETECTOR = Detector('hull', HULL_BAND, HULL_FREQ, HULL_SIGMA)


def snr_to_confidence(snr):
    """
    Map signal-to-noise ratio onto a 0..1 confidence.
    """
    s = max(float(snr), 1e-6)
    x = (np.log(s) - np.log(SNR_DETECTION_THRESHOLD)) / CONFIDENCE_SLOPE
    x = float(np.clip(x, -60.0, 60.0))
    return float(1.0 / (1.0 + np.exp(-x)))


def matched_filter(filtered_signal, template):
    """
    Back-compatible cross-correlation helper.
    Returns: (correlation, peak_index, peak_value, estimated_delay)
    """
    template_unit = template / (np.linalg.norm(template) + 1e-10)
    correlation = np.correlate(filtered_signal, template_unit, mode='same')

    peak_index = int(np.argmax(np.abs(correlation)))
    peak_value = float(np.abs(correlation[peak_index]))

    center_offset = len(filtered_signal) // 2
    estimated_delay = (peak_index - center_offset) / SAMPLE_RATE

    return correlation.tolist(), peak_index, peak_value, estimated_delay


def delay_to_distance(delay, round_trip=True):
    """
    Inverse of signal_engine.distance_to_delay().
    An ECHO travelled out and back, so the same delay means half the
    distance that a one-way DIRECT arrival would. Getting this backwards
    is what made sonar readings and shockwave readings disagree about how
    far away the same thing was.
    """
    d = abs(float(delay))
    cells = d / DELAY_PER_CELL
    return cells if round_trip else 2.0 * cells


def EstimateTargetSize(amplitude, distance, source_amplitude=SONAR_AMPLITUDE):
    """
    Work backwards from how loud the echo was to how big the thing that
    produced it must be.
    The generator built the echo as
        amp = source_amplitude * sqrt(size / 3) / (1 + alpha * distance)
    so invert that. `amplitude` is the arriving amplitude recovered by
    the detector's calibration. Returns a float; the caller clamps.
    """
    if distance is None or amplitude is None or amplitude <= 0:
        return None

    strength = amplitude * (1.0 + ATTENUATION_ALPHA * float(distance)) / source_amplitude
    if strength <= 0:
        return None
    return REFERENCE_SHIP_SIZE * (strength ** 2)


def classifySignal(signal, sample_rate=SAMPLE_RATE):
    """
    Coarse energy-based check of which band carries the event.
    Kept as a sanity check alongside the matched-filter decision in
    process_signal(), which is what actually decides.
    Returns: 'sonar', 'bomb', or 'unknown'
    """
    N = len(signal)
    X = np.fft.rfft(signal)

    freqs = np.fft.rfftfreq(N, d=1.0 / sample_rate)
    power = np.abs(X) ** 2

    sonar_mask = (freqs >= SONAR_BAND[0]) & (freqs <= SONAR_BAND[1])
    bomb_mask = (freqs >= BOMB_BAND[0]) & (freqs <= BOMB_BAND[1])

    sonar_energy = float(np.sum(power[sonar_mask]))
    bomb_energy = float(np.sum(power[bomb_mask]))

    min_energy = 0.01
    if sonar_energy < min_energy and bomb_energy < min_energy:
        return 'unknown'
    if sonar_energy > bomb_energy * CLASSIFICATION_MARGIN:
        return 'sonar'
    if bomb_energy > sonar_energy * CLASSIFICATION_MARGIN:
        return 'bomb'
    return 'unknown'


def processSignal(raw_signal):
    """
    Full DSP pipeline for one ship's received signal.
    Runs three independent detectors over the same recording:
      * SONAR channel — a bank of ping templates, one per plausible
        submarine size. The template that matches best both finds the
        echo and hints at how big the target is.
      * BOMB channel  — the low-frequency blast front.
      * HULL channel  — the high-frequency ring of a hull breaking up.
        This only ever exists when a bomb actually struck something, so
        it is what separates a HIT from a MISS. A blast with no ring is
        a splash in open water.

    Whichever channel stands furthest above its own noise floor wins, and
    the hull channel is what upgrades a plain 'bomb' to a 'bomb_hit'.

    Returns
    -------
    dict with the three display layers plus:
        detected             bool
        signal_type          'sonar' | 'bomb_hit' | 'bomb_miss' | 'unknown'
        signal_class         'sonar' | 'bomb' | 'unknown'   (coarse)
        confidence           0..1
        snr                  peak height in units of the local noise floor
        estimated_distance   cells, under the hypothesis matching signal_type
        estimated_distance_echo    cells, if this were a round-trip echo
        estimated_distance_direct  cells, if this were a one-way arrival
        estimated_size       cells, best guess at the target's size
        hull_ring            bool, was a hull heard breaking up
    """
    signal = np.array(raw_signal, dtype=float)
    # ---- sonar template bank (one hypothesis per submarine size) ----
    sonar_runs = [(d, d.run(signal)) for d in _SONAR_DETECTORS]
    best_det, sonar = max(sonar_runs, key=lambda pair: pair[1]['snr'])
    best_size_hyp = best_det.size

    # ---- bomb blast and hull ring ----
    bomb = _BOMB_DETECTOR.run(signal)
    hull = _HULL_DETECTOR.run(signal)
    detected = False
    signal_type = 'unknown'
    signal_class = 'unknown'
    est_dist = est_dist_echo = est_dist_direct = None
    est_size = None
    # A hull ring only exists when a blast broke something, so hearing
    # one is the hit. We still want some corroboration from the blast
    # channel before calling it, otherwise a stray noise spike in the
    # hull band could announce a hit during quiet ocean — but we accept
    # a weaker blast than the full threshold, because at long range the
    # low-frequency thump fades faster than the ring does.
    hull_corroborated = bomb['detected'] or bomb['snr'] >= 0.6 * SNR_DETECTION_THRESHOLD

    if hull['detected'] and hull_corroborated:
        detected = True
        signal_type = 'bomb_hit'
        signal_class = 'bomb'
        chosen = bomb if bomb['detected'] else hull
        # Range comes from the blast front when we have it; otherwise
        # back it out of the ring, which arrives a fixed lag later.
        if bomb['detected']:
            ranging_delay = bomb['delay']
        else:
            ranging_delay = max(0.0, hull['delay'] - HULL_RING_LAG)
        est_dist_direct = delay_to_distance(ranging_delay, round_trip=False)
        est_dist_echo = delay_to_distance(ranging_delay, round_trip=True)
        est_dist = est_dist_direct
        # Ring loudness scales with the struck boat's size.
        est_size = EstimateTargetSize(
            hull['amplitude'], est_dist_direct,
            source_amplitude=HULL_AMPLITUDE,
        )
    elif bomb['detected'] and bomb['snr'] >= sonar['snr']:
        # Blast with no hull ring: the bomb went into open water.
        detected = True
        signal_type = 'bomb_miss'
        signal_class = 'bomb'
        chosen = bomb
        est_dist_direct = delay_to_distance(bomb['delay'], round_trip=False)
        est_dist_echo = delay_to_distance(bomb['delay'], round_trip=True)
        est_dist = est_dist_direct
    elif sonar['detected']:
        detected = True
        signal_type = 'sonar'
        signal_class = 'sonar'
        chosen = sonar
        est_dist_echo = delay_to_distance(sonar['delay'], round_trip=True)
        est_dist_direct = delay_to_distance(sonar['delay'], round_trip=False)
        est_dist = est_dist_echo
        est_size = EstimateTargetSize(sonar['amplitude'], est_dist_echo,
                                        source_amplitude=SONAR_AMPLITUDE * ECHO_GAIN)
    else:
        # Nothing cleared the bar. Show the sonar channel by default, and
        # still report the confidence we actually measured rather than a
        # hard zero — "we heard something, but not enough of it" is real
        # information and the meter should say so.
        chosen = sonar if sonar['snr'] >= bomb['snr'] else bomb

    confidence = chosen['confidence']
    snr = chosen['snr']

    # Blend the shape-matched size hypothesis with the amplitude-derived
    # one, then clamp to something a submarine could plausibly be.
    if est_size is not None:
        if signal_type == 'sonar':
            est_size = 0.5 * est_size + 0.5 * best_size_hyp
        est_size = int(round(min(MAX_REPORTED_SIZE,
                                 max(MIN_REPORTED_SIZE, est_size))))

    return {
        # Raw waveform: displayed on the 'noise' canvas so the user sees
        # the unfiltered signal and can compare it against the filtered one.
        'raw_signal':      raw_signal,
        # Bandpass-filtered signal: displayed on the 'filtered' canvas.
        # Visually distinct from the raw signal — out-of-band noise is
        # gone, leaving only the band of interest.
        'noise_component': chosen['filtered'].tolist(),
        # Matched-filter envelope: peaks indicate detection.
        'detected_signal': chosen['correlation'],
        'detected':        detected,
        'signal_type':     signal_type,
        'signal_class':    signal_class,
        'confidence':      round(float(confidence), 4),
        'snr':             round(float(snr), 2),
        'estimated_distance':        round(est_dist, 2) if est_dist is not None else None,
        'estimated_distance_echo':   round(est_dist_echo, 2) if est_dist_echo is not None else None,
        'estimated_distance_direct': round(est_dist_direct, 2) if est_dist_direct is not None else None,
        'estimated_size':  est_size,
        'hull_ring':       bool(hull['detected']),
        'peak_sample_index': chosen['peak_index'],
        # Per-channel diagnostics — handy for the write-up and for tuning.
        'channels': {
            'sonar': {'snr': round(sonar['snr'], 2),
                      'peak': round(sonar['peak_value'], 4),
                      'size_hypothesis': best_size_hyp},
            'bomb':  {'snr': round(bomb['snr'], 2),
                      'peak': round(bomb['peak_value'], 4)},
            'hull':  {'snr': round(hull['snr'], 2),
                      'peak': round(hull['peak_value'], 4)},
        },
    }
