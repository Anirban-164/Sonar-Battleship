import numpy as np
import math

# ------------------------------------------------------------
# Constants
# ------------------------------------------------------------

SAMPLE_RATE = 200 # samples/sec
SIGNAL_DURATION = 3.0 # seconds of signal per snapshot
NUM_SAMPLES = int(SAMPLE_RATE * SIGNAL_DURATION)

# Every generator places its pulse at PULSE_ORIGIN_OFFSET + delay, and the
# matched-filter templates in signal_processor.py are built at exactly the
# same offset. Keep these in sync — if a generator uses a different offset
# than the template, every distance estimate comes out biased by the
# difference (this used to be 0.5s for echoes, 0.3s for incoming sonar and
# 0.4s for shockwaves, which is why the readouts disagreed with reality).
PULSE_ORIGIN_OFFSET = 0.30

# Sonar pulse
SONAR_FREQ = 5.0 # carrier
SONAR_SIGMA = 0.08 # Gaussian width (sec)
SONAR_AMPLITUDE = 1.0 # Peak amplitude (b4 attenuation)
ECHO_GAIN = 1.4 # active sonar advantage --> sender correlates a known waveform, passive listener doesn't
PULSE_TUNING = 0.12 # increase in the pulse's width for every extra cell of submarine length

# fire shockwave (the blast itself — low, broad, no fine structure)
BOMB_FREQ = 2.0 # lower, broader
BOMB_SIGMA = 0.15 # Wider Gaussian
BOMB_AMPLITUDE = 0.7

# Hull rupture ring — ONLY produced when a bomb actually strikes a hull.
# A blast in open water is just the low-frequency shockwave above; steel
# breaking up rings at a much higher frequency for a short time. This is
# the acoustic feature that lets the detector call "hit" vs "miss"
# instead of reporting one generic "shockwave" for both.
HULL_FREQ = 12.0
HULL_SIGMA = 0.06
# Loud on purpose. A hull failing under a blast releases far more energy
# than the water around it, and the whole point of this signature is that
# the attacker can confirm a hit acoustically from across the board — so
# it has to survive the trip. Tuned so a hit is called correctly ~95% of
# the time at full board range, while a miss is never called a hit.
HULL_AMPLITUDE = 1.6
HULL_RING_LAG = 0.12 # sec after the blast front that the hull lets go

# Environment
NOISE_LEVEL = 0.15 # sigma of AWGN
# Distance decay coefficient. This was 0.3, which was tuned for a single
# 10-wide grid — but the two fleets sit side by side, so every real
# sight line is 10-21 cells and an echo from that far arrived at about a
# fifth of its source amplitude. Nothing was ever reliably detectable and
# the contacts players did see were mostly the detector misreading noise.
# At 0.12 a big boat is found consistently, a small one at long range is
# a coin flip, and the noise level still drives the difference.
ATTENUATION_ALPHA = 0.12
# Seconds of ROUND-TRIP delay per grid cell — i.e. the delay on an echo
# that goes out one cell and comes back. A one-way arrival takes half of
# it. Sized so that the longest possible sight line across the unified
# 20x10 board (about 21 cells) still lands its echo inside the 3-second
# recording window: 0.30 + 21*0.12 = 2.82s.
DELAY_PER_CELL = 0.12

# Beam geometry — one number, used by every beam test in the project.
BEAM_HALF_WIDTH = 9.0   # degrees either side of the chosen bearing

# Target strength scales with submarine size. Amplitude goes with the
# square root of the reflecting area, so a 5-cell boat comes back
# noticeably louder than a 3-cell boat but not 5/3 as loud — and the
# detector can invert this to estimate what it just found.
REFERENCE_SHIP_SIZE = 3.0

# A blast only rings a hull it actually touches.
BOMB_BLAST_RADIUS = 1.0  # cells

# A transmitting sonar is not a laser. Most of its energy goes into the
# main lobe along the chosen bearing, but a real transducer also radiates
# off-axis, and a passive hydrophone that is only listening is sensitive
# enough to pick that up. The level falls away smoothly with angle rather
# than cutting off at the edge of the beam: a boat just outside the cone
# hears the ping almost as well as one inside it, a boat off to the side
# hears something faint, and a boat behind the transmitter hears
# essentially nothing.
#
# This is what gives active sonar its cost. The beam has to point at the
# enemy fleet to find it — and that is precisely the bearing on which the
# enemy fleet hears you best.
#
# Tuned so that, at the default noise level, a fleet of three hears a ping
# aimed at them about 94% of the time but can only turn it into a full
# bearing fix about half the time; a ping 60 degrees off their bearing is
# heard about one time in five, and one aimed away is not heard at all.
SIDE_LOBE_FALLOFF_DEG = 45.0    # degrees for the side lobes to fall by 1/e


# ########## core signal generators ##############
def time_axis():
    """ generates the time axis for a signal snapshot """
    t = np.linspace(0, SIGNAL_DURATION, NUM_SAMPLES, endpoint = False)

    return t


def gaussian_ping(t, freq, sigma, amp, center):
    """
    - generates a ping
    Formula: p(t) = A * e^(- (t-c)^2 / (2 * sigma^2)) * sin(wt)
    - the gaussian envelope makes it a short burst rather than an infinite wave -->
    useful for matched filtering later...
    """
    envelope = np.exp(-0.5 * (((t - center) / sigma) ** 2))
    p = amp * envelope * np.sin(2 * np.pi * freq * t)
    
    return p


def attenuate(amp, dist):
    """
    signal decays with distance --> energy loss as it travels through water
    Formula: A_received = A_source / (1 + alpha * dist)
    """
    decay_factor = 1 + ATTENUATION_ALPHA * dist
    return amp / decay_factor



def target_strength(size):
    """
    How much sound comes back depends on how much of the target the wave meets...
    - bigger sub --> larger target --> louder sound
    - taking 3-cell boat as reference
    """
    ratio = max(1.0, float(size)) / REFERENCE_SHIP_SIZE
    return math.sqrt(ratio) # amplitude tracks the square root of the reflecting area


def size_pulse_width(size):
    """
    Bigger boats affect the echo slightly --> more hull length means the
    return arrives over a longer window
    - effect might be small but it might give the detector a clue about target size
    """
    diff = float(size) - REFERENCE_SHIP_SIZE
    factor = 1.0 + PULSE_TUNING * diff

    return SONAR_SIGMA * factor


def distance_to_delay(dist, round_trip = True):
    """
    finds time delay based on grid distance

    round_trip = True --> a sonar echo --> bidirectional path (out and back)
    round_trip = False --> a direct arrival (hostile ping sweeping past us or a blast wavefront) --> one way only
    """
    round_trip_delay = dist * DELAY_PER_CELL
    return round_trip_delay if round_trip else 0.5 * round_trip_delay


def generate_ocean_noise(num_samples = NUM_SAMPLES, rng = None):
    """
    Generate pure ocean ambient noise (AWGN)
    - if rng is provided, uses it for deterministic output
    """
    if rng is not None:
        return rng.normal(0, NOISE_LEVEL, num_samples)
    return np.random.normal(0, NOISE_LEVEL, num_samples)


# ################ sonar  ping ################
def bearing_offset(origin, target, angle):
    """
    How many degrees off the chosen bearing the target sits, 0..180.
    Returns 0.0 when the target is the origin itself.
    """
    ori_r, ori_c = origin
    tr, tc = target
    dr = tr - ori_r
    dc = tc - ori_c

    if dr == 0 and dc == 0:
        return 0.0

    cell_bearing = math.degrees(math.atan2(dc, -dr))
    if cell_bearing < 0:
        cell_bearing += 360

    diff = abs(cell_bearing - angle) % 360
    if diff > 180:
        diff = 360 - diff
    return diff


def _in_beam(origin, target, angle, half_width = BEAM_HALF_WIDTH):
    """
    checks if the target is in the way of the sonar beam
    """
    offset = bearing_offset(origin, target, angle)
    return offset <= half_width


def transducer_gain(origin, target, angle, half_width=BEAM_HALF_WIDTH):
    """
    Radiation pattern of the transmitting sonar, as heard from target...
    - 1.0 anywhere inside the main lobe, then decaying exponentially with how far off-axis the listener sits
    - Used for passive counter-detection
    Formula: level = L * e^(-(offset - half_width) / falloff_deg)
    """
    offset = bearing_offset(origin, target, angle)
    if offset <= half_width:
        return 1.0

    expo = -(offset - half_width) / SIDE_LOBE_FALLOFF_DEG
    return math.exp(expo)


def _enemy_col_offset(grid_size, side):
    """
    Both fleets live in one unified coordinate space that is 2*grid_size wide
    - returns the shift to apply to an ENEMY column to bring it into
    my frame
    """
    return grid_size if side == 'left' else -grid_size


def _ship_contains(ship, row, col):
    """ checks if the ship occupies the given cell"""
    return any(c[0] == row and c[1] == col for c in ship.get('cells', []))


def find_beam_blocker(origin, angle_deg, my_ships, max_range = None):
    """
    Checks if any friendly ship is blocking the sonar beam.
    - skip the boat firing the ping
    - skip sunk ships
    Returns (distance, size) of the nearest blocker, or (None, None).
    """
    ori_r, ori_c = origin
    blocker_dist = None
    blocker_size = None

    for ship in my_ships:
        if ship.get('is_sunk', False):
            continue
            
        if _ship_contains(ship, ori_r, ori_c):
            continue

        for cell in ship.get('cells', []):
            cr, cc = cell[0], cell[1]
            dr = cr - ori_r
            dc = cc - ori_c
            dist = math.sqrt(dr ** 2 + dc ** 2)
            
            if dist < 1e-6 or (max_range and dist > max_range):
                continue
                
            if not _in_beam(origin, (cr, cc), angle_deg):
                continue
                
            if blocker_dist is None or dist < blocker_dist:
                blocker_dist = dist
                blocker_size = int(ship.get('size', len(ship.get('cells', []))) or 0)

    return blocker_dist, blocker_size


def generate_sonar_echo(origin, angle_deg, my_ships, enemy_ships, grid_size, side = 'left', seed = None):
    """
    Generates echo signals received by our ships after firing a sonar ping.
    Possible outcomes:
    - Friendly hull blocks the beam --> return --> no enemy data
    - Enemy hull in the beam --> contact --> amplitude and width depend on target size
    - Empty water --> ocean noise
    - seed makes the noise deterministic so the table and graph always agree
    """
    t = time_axis()
    rng = np.random.default_rng(seed) if seed is not None else None
    ori_r, ori_c = origin
    col_offset = _enemy_col_offset(grid_size, side)

    # find nearest enemy hull in the beam
    min_enemy_dist = np.inf
    enemy_size = None

    for ship in enemy_ships:
        if ship.get('is_sunk', False):
            continue

        cells = ship.get('cells', [])
        actual_size = int(ship.get('size', len(cells)) or len(cells))
        cells_in_beam = 0
        nearest_cell = np.inf

        for cell in cells:
            cr, cc = cell[0], cell[1]
            shifted_col = cc + col_offset  # enemy's col is shifted into our frame
            
            dr = cr - ori_r
            dc = shifted_col - ori_c
            dist = max(0.1, math.sqrt(dr ** 2 + dc ** 2))

            if _in_beam(origin, (cr, shifted_col), angle_deg):
                cells_in_beam += 1
                nearest_cell = min(nearest_cell, dist)

        if cells_in_beam > 0 and nearest_cell < min_enemy_dist:
            min_enemy_dist = nearest_cell
            # effective size depends on how much of the boat we can 'see'
            enemy_size = actual_size if cells_in_beam >= actual_size else max(1, cells_in_beam)

    has_enemy = min_enemy_dist < np.inf

    # check for friendly blockers
    blocker_dist, blocker_size = find_beam_blocker(origin, angle_deg, my_ships)
    is_blocked = blocker_dist is not None and (not has_enemy or blocker_dist < min_enemy_dist)

    # determine echo properties
    if is_blocked:
        echo_dist = blocker_dist
        echo_size = blocker_size or int(REFERENCE_SHIP_SIZE)
        true_size, true_dist = None, None
    elif has_enemy:
        echo_dist = min_enemy_dist
        echo_size = enemy_size or int(REFERENCE_SHIP_SIZE)
        true_size, true_dist = echo_size, min_enemy_dist
    else:
        echo_dist, echo_size = None, None
        true_size, true_dist = None, None

    has_echo = echo_dist is not None
    result = {}


    # create the waveform for each hydrophone
    for idx, ship in enumerate(my_ships):
        cells = ship.get('cells', [])
        # distance from this listening sub to the sub that fired the ping
        dist_to_source = np.inf
        for c in cells:
            dist = math.sqrt((c[0] - ori_r) ** 2 + (c[1] - ori_c) ** 2)
            if dist < dist_to_source:
                dist_to_source = dist
                
        if dist_to_source == np.inf:
            dist_to_source = 0.0

        signal = generate_ocean_noise(len(t), rng=rng)
        delay = None
        amp = None

        if has_echo:
            delay = distance_to_delay(echo_dist, round_trip=True)
            
            # echo decays twice: once going to the target, once coming back to the listener
            # ECHO_GAIN compensates for the round-trip loss and models the active sonar advantage
            base_amp = attenuate(SONAR_AMPLITUDE * ECHO_GAIN * target_strength(echo_size), echo_dist)

            listener_decay = attenuate(1.0, dist_to_source)
            amp = base_amp * listener_decay

            pulse_time = PULSE_ORIGIN_OFFSET + delay
            if pulse_time < SIGNAL_DURATION:
                echo_pulse = gaussian_ping(t, SONAR_FREQ, size_pulse_width(echo_size), amp, pulse_time)
                signal += echo_pulse

        result[idx] = {
            'signal': signal.tolist(),
            'time': t.tolist(),
            'has_echo': has_echo,
            'echo_delay': float(delay) if delay is not None else None,
            'echo_amplitude': float(amp) if amp is not None else None,
            'blocked': bool(is_blocked),
            'blocked_by_size': int(blocker_size) if is_blocked and blocker_size else None,
            'blocker_distance': round(float(blocker_dist), 2) if is_blocked else None,
            'target_size': true_size,
            'target_distance': round(float(true_dist), 2) if true_dist is not None else None,
        }
    return result


# ============================================================
# Scenario 2: Enemy Sonar passes near our ships
# ============================================================
def generate_incoming_sonar_signals(enemy_origin, angle_deg, my_ships, grid_size, my_position = 'left', seed = None):
    """
    Simulates receiving an enemy's sonar ping.
    - direct, one-way
    - closer ships get a stronger signal
    """
    t = time_axis()
    enemy_r, enemy_c = enemy_origin
    col_offset = -grid_size if my_position == 'left' else grid_size
    origin_pt = (enemy_r, enemy_c)
    rng = np.random.default_rng(seed) if seed is not None else None

    # amplitude floor: if the received signal would be weaker than this,
    # don't bother adding it — it's buried so far below the noise that
    # the DSP shouldn't be picking it up. Without this, every ship in
    # the fleet gets a tiny pulse and the detector false-triggers on
    # ships that are nowhere near the beam.
    amp_floor = NOISE_LEVEL * 2.0

    result = {}
    for idx, ship in enumerate(my_ships):
        signal = generate_ocean_noise(len(t), rng=rng)
        best_amp = 0.0
        best_delay = None
        in_beam = False

        for cell in ship.get('cells', []):
            cr, cc = cell[0], cell[1]
            shifted_col = cc + col_offset
            
            dr = cr - enemy_r
            dc = shifted_col - enemy_c
            dist = math.sqrt(dr ** 2 + dc ** 2)

            # check if this part of the sub is inside the main sonar cone
            in_main_lobe = _in_beam(origin_pt, (cr, shifted_col), angle_deg)
            lobe_gain = transducer_gain(origin_pt, (cr, shifted_col), angle_deg)

            delay = distance_to_delay(dist, round_trip=False)
            amp = attenuate(SONAR_AMPLITUDE * lobe_gain, dist)

            if amp > best_amp:
                best_amp = amp
                best_delay = delay
                in_beam = in_main_lobe

        # only inject a pulse if the amplitude actually stands above the noise —
        # otherwise the ship genuinely can't hear it and shouldn't detect anything
        detected = best_amp >= amp_floor and best_delay is not None

        if detected:
            pulse_time = PULSE_ORIGIN_OFFSET + best_delay
            if pulse_time < SIGNAL_DURATION:
                ping_pulse = gaussian_ping(t, SONAR_FREQ, SONAR_SIGMA, best_amp, pulse_time)
                signal += ping_pulse
            else:
                detected = False

        result[idx] = {
            'signal': signal.tolist(),
            'time': t.tolist(),
            'has_echo': detected,
            'echo_delay': float(best_delay) if best_delay is not None else None,
            'echo_amplitude': float(best_amp) if best_amp > 0 else None,
            'in_main_lobe': bool(in_beam),
            'blocked': False,
            'blocked_by_size': None,
            'blocker_distance': None,
            'target_size': None,
            'target_distance': None,
        }
    return result


# ============================================================
# Scenario 3: Fire/Bomb Shockwave
# ============================================================

def generate_bomb_shockwave_signals(bomb_coord, my_ships, grid_size, my_position = 'left', target_side = 'enemy', hit = False, hit_ship_size = None, seed = None):
    """
    Generates acoustic signals for a bomb explosion.
    - MISS --> low-frequency shockwave
    - HIT --> shockwave + higher-frequency hull rupture ring (metal screeching sound or whatever you say) --> lets the detector know it's a hit
    """
    t = time_axis()
    bomb_r, bomb_c = bomb_coord

    # shift columns if the bomb landed on the enemy's grid
    if target_side == 'mine':
        col_offset = 0
    else:
        col_offset = -grid_size if my_position == 'left' else grid_size
    ring_size = hit_ship_size or REFERENCE_SHIP_SIZE
    rng = np.random.default_rng(seed) if seed is not None else None

    result = {}
    for idx, ship in enumerate(my_ships):
        signal = generate_ocean_noise(len(t), rng=rng)
        heard_shockwave = False
        shock_delay = None
        shock_amp = None

        # find closest point on this sub to the blast
        min_dist = np.inf
        for cell in ship.get('cells', []):
            cr, cc = cell[0], cell[1]
            shifted_col = cc + col_offset
            dr = cr - bomb_r
            dc = shifted_col - bomb_c
            min_dist = min(min_dist, math.sqrt(dr ** 2 + dc ** 2))

        # shockwaves dissipate completely after 1.5 grid widths
        max_range = grid_size * 1.5
        if min_dist <= max_range:
            heard_shockwave = True
            shock_delay = distance_to_delay(min_dist, round_trip=False)
            shock_amp = attenuate(BOMB_AMPLITUDE, min_dist)

            pulse_time = PULSE_ORIGIN_OFFSET + shock_delay

            if pulse_time < SIGNAL_DURATION:
                #  primary blast wave
                blast_pulse = gaussian_ping(t, BOMB_FREQ, BOMB_SIGMA, shock_amp, pulse_time)
                signal += blast_pulse

                # hull rupture ring --> only for direct hit...
                if hit:
                    ring_amp = attenuate(HULL_AMPLITUDE * target_strength(ring_size), min_dist)

                    ring_time = pulse_time + HULL_RING_LAG
                    if ring_time < SIGNAL_DURATION:
                        ring_pulse = gaussian_ping(t, HULL_FREQ, HULL_SIGMA, ring_amp, ring_time)
                        signal += ring_pulse

        result[idx] = {
            'signal': signal.tolist(),
            'time': t.tolist(),
            'has_echo': heard_shockwave,
            'echo_delay': float(shock_delay) if shock_delay is not None else None,
            'echo_amplitude': float(shock_amp) if shock_amp is not None else None,
            'blocked': False,
            'blocked_by_size': None,
            'blocker_distance': None,
            'target_size': int(ring_size) if hit else None,
            'target_distance': round(float(min_dist), 2) if heard_shockwave else None,
            'was_hit': bool(hit),
        }

    return result


# ============================================================
# Idle Ocean Noise (for continuous display)
# ============================================================

def generate_idle_signals(num_ships):
    """
    Generates continuous background ocean noise for idle mode
    """
    t = time_axis()
    result = {}

    for idx in range(num_ships):
        signal = generate_ocean_noise(len(t))
        result[idx] = {
            'signal': signal.tolist(),
            'time': t.tolist(),
            'has_echo': False,
            'echo_delay': None,
            'echo_amplitude': None,
            'blocked': False,
            'blocked_by_size': None,
            'blocker_distance': None,
            'target_size': None,
            'target_distance': None,
        }
        
    return result
