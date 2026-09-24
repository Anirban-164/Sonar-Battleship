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
SONAR_FREQ = 5.0         # carrier
SONAR_SIGMA = 0.08       # Gaussian width (sec)
SONAR_AMPLITUDE = 1.0    # Peak amplitude (b4 attenuation)

# fire shockwave (the blast itself — low, broad, no fine structure)
BOMB_FREQ = 2.0          # lower, broader
BOMB_SIGMA = 0.15        # Wider Gaussian
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
HULL_RING_LAG = 0.12     # sec after the blast front that the hull lets go

# Environment
NOISE_LEVEL = 0.15       # sigma of AWGN
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
SIDE_LOBE_LEVEL = 0.90          # level immediately outside the main lobe
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
    Reduces amplitude based on distance.
    Formula: A_received = A_source / (1 + alpha * dist)
    Simulates sound energy loss as it travels through water.
    """
    return amp / (1 + ATTENUATION_ALPHA * dist)


def target_strength(size):
    """
    How loud a submarine of `size` cells comes back compared to the
    reference 3-cell boat. Amplitude tracks the square root of the
    reflecting area, so this is sqrt(size / 3).
    signal_processor.estimate_target_size() is the exact inverse.
    """
    return math.sqrt(max(1.0, float(size)) / REFERENCE_SHIP_SIZE)


def size_pulse_width(size):
    """
    Bigger boats smear the echo slightly — more hull length means the
    return arrives over a longer window. Small effect, but it gives the
    detector a second, independent cue about target size.
    """
    return SONAR_SIGMA * (1.0 + 0.12 * (float(size) - REFERENCE_SHIP_SIZE))


def distance_to_delay(dist, round_trip=True):
    """
    Maps grid distance to a time delay in seconds.

    round_trip=True  -> a sonar ECHO: out to the target and back.
    round_trip=False -> a DIRECT arrival (enemy's ping sweeping past us,
                        or a blast wavefront reaching us). One way only.

    signal_processor.delay_to_distance() inverts this, and it needs to
    know which case it is — that's why the detector reports a distance
    under both hypotheses and the caller picks the one matching the event.
    """
    round_trip_delay = dist * DELAY_PER_CELL
    return round_trip_delay if round_trip else 0.5 * round_trip_delay


def generate_ocean_noise(num_samples=NUM_SAMPLES):
    """
    Generate pure ocean ambient noise (AWGN).
    Models the background acoustic environment: thermal noise,
    biological sounds, wave action, and distant shipping — all
    of which superimpose to approximate a Gaussian random process
    by the Central Limit Theorem.
    Returns
    -------
    np.ndarray
        Noise signal of shape (num_samples,)
    """
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


def _in_beam(origin, target, angle, half_width=BEAM_HALF_WIDTH):
    """
    Returns true if target is in beam centered at angle
    """
    return bearing_offset(origin, target, angle) <= half_width


def transducer_gain(origin, target, angle, half_width=BEAM_HALF_WIDTH):
    """
    Radiation pattern of the transmitting sonar, as heard from `target`.

    1.0 anywhere inside the main lobe, then decaying exponentially with
    how far off-axis the listener sits. Used for passive counter-detection
    — the active echo path still only cares about the main lobe, because
    a side-lobe return is far too weak to survive the round trip.
    """
    off = bearing_offset(origin, target, angle)
    if off <= half_width:
        return 1.0
    return SIDE_LOBE_LEVEL * math.exp(-(off - half_width) / SIDE_LOBE_FALLOFF_DEG)


def _enemy_col_offset(grid_size, side):
    """
    Both fleets live in one unified coordinate space that is 2*grid_size
    wide: the left player occupies columns 0..grid_size-1 and the right
    player occupies columns grid_size..2*grid_size-1.

    This returns the shift to apply to an ENEMY column to bring it into
    my frame. My own cells never get shifted.
    """
    return grid_size if side == 'left' else -grid_size


def _ship_contains(ship, row, col):
    """Does this ship occupy the given cell?"""
    return any(c[0] == row and c[1] == col for c in ship.get('cells', []))


def find_beam_blocker(origin, angle_deg, my_ships, max_range=None):
    """
    Walk the player's OWN fleet and find the nearest friendly hull sitting
    in the beam. A sonar pulse cannot see through a submarine — if one of
    your own boats is parked in front of the transducer, the pulse hits it
    and comes straight back, and you learn nothing about the enemy.

    The boat the ping is fired FROM is skipped (it can't block itself),
    and so are wrecks — a sunk hull has gone to the bottom and is out of
    the beam.

    Returns (distance, size) of the nearest blocker, or (None, None).
    """
    ori_r, ori_c = origin

    blocker_dist = None
    blocker_size = None

    for ship in my_ships:
        if ship.get('is_sunk', False):
            continue
        # The origin boat is the one doing the pinging.
        if _ship_contains(ship, ori_r, ori_c):
            continue

        for cell in ship.get('cells', []):
            cr, cc = cell[0], cell[1]
            dr = cr - ori_r
            dc = cc - ori_c
            dist = math.sqrt(dr ** 2 + dc ** 2)
            if dist < 1e-6:
                continue
            if max_range is not None and dist > max_range:
                continue
            if not _in_beam(origin, (cr, cc), angle_deg, BEAM_HALF_WIDTH):
                continue
            if blocker_dist is None or dist < blocker_dist:
                blocker_dist = dist
                blocker_size = int(ship.get('size', len(ship.get('cells', []))) or 0)

    return blocker_dist, blocker_size


def generate_sonar_echo(origin, angle_deg, my_ships, enemy_ships, grid_size, side='left'):
    """
    Generate the signals received by each of the player's ships
    after a sonar ping.

    The ping travels outward from the origin ship cell along the chosen
    bearing. Three things can happen:

      1. A FRIENDLY hull is in the beam first — the pulse bounces off our
         own boat and never reaches the enemy. We return that echo and
         flag the ping as blocked. No enemy information at all.
      2. An ENEMY hull is the first thing in the beam — we get a real
         contact. The echo is louder and slightly wider for bigger
         submarines, which is what lets the detector guess the target's
         size instead of just saying "something is out there".
      3. Nothing in the beam — pure ocean noise.

    Each of the player's ships "hears" whatever came back, attenuated by
    its own distance from the origin, so the originating boat always has
    the cleanest copy.

    Returns
    -------
    dict
        {
            ship_index: {
                'signal': [float, ...],   # 600 samples
                'time': [float, ...],
                'has_echo': bool,
                'echo_delay': float or None,
                'echo_amplitude': float or None,
                'blocked': bool,          # friendly hull ate the ping
                'blocked_by_size': int or None,
                'blocker_distance': float or None,
                'target_size': int or None,      # ground truth, for debugging
                'target_distance': float or None,
            },
            ...
        }
    """

    t = time_axis()

    ori_r, ori_c = origin
    col_offset = _enemy_col_offset(grid_size, side)

    # ---- 1. Where is the nearest enemy hull along this bearing? ----
    min_enemy_dist = float('inf')
    enemy_size = None

    for ship in enemy_ships:
        if ship.get('is_sunk', False):
            continue

        cells = ship.get('cells') or []
        ship_size = int(ship.get('size', len(cells)) or len(cells))

        # How much of this boat is actually inside the beam? A submarine
        # lying broadside across the beam presents more of itself than one
        # pointing straight at us, and that shows up in the echo.
        cells_in_beam = 0
        nearest_for_ship = float('inf')

        for cell in cells:
            cr, cc = cell[0], cell[1]
            eff_cc = cc + col_offset  # effective col in the unified frame
            dr = cr - ori_r
            dc = eff_cc - ori_c
            dist = math.sqrt(dr ** 2 + dc ** 2)
            if dist < 0.1:
                dist = 0.1

            if _in_beam(origin, (cr, eff_cc), angle_deg, BEAM_HALF_WIDTH):
                cells_in_beam += 1
                nearest_for_ship = min(nearest_for_ship, dist)

        if cells_in_beam and nearest_for_ship < min_enemy_dist:
            min_enemy_dist = nearest_for_ship
            # Effective size is capped by how much of the boat we can see.
            enemy_size = ship_size if cells_in_beam >= ship_size else max(1, cells_in_beam)

    has_enemy = min_enemy_dist < float('inf')

    # ---- 2. Is one of our own boats in the way? ----
    blocker_dist, blocker_size = find_beam_blocker(origin, angle_deg, my_ships)

    blocked = blocker_dist is not None and (not has_enemy or blocker_dist < min_enemy_dist)

    # ---- 3. Decide what actually comes back ----
    if blocked:
        # Friendly hull. Strong, close return — and useless.
        echo_distance = blocker_dist
        echo_size = blocker_size or int(REFERENCE_SHIP_SIZE)
        target_size_truth = None
        target_dist_truth = None
    elif has_enemy:
        echo_distance = min_enemy_dist
        echo_size = enemy_size or int(REFERENCE_SHIP_SIZE)
        target_size_truth = echo_size
        target_dist_truth = min_enemy_dist
    else:
        echo_distance = None
        echo_size = None
        target_size_truth = None
        target_dist_truth = None

    has_echo = echo_distance is not None

    # ---- 4. Render the waveform for every one of our hydrophones ----
    result = {}
    for idx, ship in enumerate(my_ships):
        # Distance from the NEAREST cell of this boat to the sonar origin.
        cells = ship.get('cells') or []
        dist_to_origin = min(
            (math.sqrt((c[0] - ori_r) ** 2 + (c[1] - ori_c) ** 2) for c in cells),
            default=0.0,
        )

        signal = generate_ocean_noise(len(t))
        echo_delay = None
        echo_amp = None

        if has_echo:
            # Round trip: out to the target and back again.
            echo_delay = distance_to_delay(echo_distance, round_trip=True)

            base_amp = attenuate(
                SONAR_AMPLITUDE * target_strength(echo_size), echo_distance
            )
            # Further attenuated by how far this hydrophone sits from the
            # boat that actually transmitted.
            ship_attenuation = attenuate(1.0, dist_to_origin)
            echo_amp = base_amp * ship_attenuation

            pulse_center = PULSE_ORIGIN_OFFSET + echo_delay
            if pulse_center < SIGNAL_DURATION:
                echo = gaussian_ping(
                    t, SONAR_FREQ, size_pulse_width(echo_size), echo_amp, pulse_center
                )
                signal += echo

        result[idx] = {
            'signal': signal.tolist(),
            'time': t.tolist(),
            'has_echo': has_echo,
            'echo_delay': float(echo_delay) if echo_delay is not None else None,
            'echo_amplitude': float(echo_amp) if echo_amp is not None else None,
            'blocked': bool(blocked),
            'blocked_by_size': int(blocker_size) if blocked and blocker_size else None,
            'blocker_distance': round(float(blocker_dist), 2) if blocked else None,
            'target_size': target_size_truth,
            'target_distance': (round(float(target_dist_truth), 2)
                                if target_dist_truth is not None else None),
        }
    return result


# ============================================================
# Scenario 2: Enemy Sonar passes near our ships
# ============================================================
def generate_incoming_sonar_signals(enemy_origin, angle_deg, my_ships, grid_size,
                                    my_position='left'):
    """
    When the enemy fires sonar, the ping pulse travels through the water.
    Each of our ships in or near the beam path picks up the incoming
    signal. The nearest ship gets the highest amplitude bump; farther
    ships get weaker signals.

    This is a DIRECT arrival (not an echo), so there's no round trip —
    the delay is one-way.

    Parameters
    ----------
    enemy_origin : (row, col)
        Where the enemy's sonar originated, in the enemy's own grid.
    angle_deg : float
        Enemy's sonar bearing
    my_ships : list of dict
    grid_size : int
    my_position : str
    """
    t = time_axis()
    enemy_origin_row, enemy_origin_col = enemy_origin

    # The enemy's origin lives on the enemy's grid. Shift MY columns into
    # the enemy's frame so the bearing maths lines up.
    col_offset = -grid_size if my_position == 'left' else grid_size

    result = {}
    for idx, ship in enumerate(my_ships):
        signal = generate_ocean_noise(len(t))
        has_contact = False
        contact_delay = None
        contact_amp = None
        in_beam = False

        for cell in ship['cells']:
            cr, cc = cell[0], cell[1]
            effective_cc = cc + col_offset
            dr = cr - enemy_origin_row
            dc = effective_cc - enemy_origin_col
            dist = math.sqrt(dr ** 2 + dc ** 2)

            # Inside the main lobe we hear it loud and clear; outside it
            # we still hear the transducer's side lobes, much fainter.
            # Same beam width as everywhere else — it used to be doubled
            # here, which let defenders hear pings aimed nowhere near them
            # at full strength.
            origin_pt = (enemy_origin_row, enemy_origin_col)
            in_main_lobe = _in_beam(origin_pt, (cr, effective_cc),
                                    angle_deg, BEAM_HALF_WIDTH)
            lobe_gain = transducer_gain(origin_pt, (cr, effective_cc),
                                        angle_deg, BEAM_HALF_WIDTH)

            delay = distance_to_delay(dist, round_trip=False)
            # Direct arrival: one-way from the enemy transducer to us.
            # Full sonar amplitude × lobe gain (no arbitrary dampening).
            amp = attenuate(SONAR_AMPLITUDE * lobe_gain, dist)

            if not has_contact or amp > contact_amp:
                has_contact = True
                contact_delay = delay
                contact_amp = amp
                in_beam = in_main_lobe

        if has_contact and contact_delay is not None:
            pulse_center = PULSE_ORIGIN_OFFSET + contact_delay
            if pulse_center < SIGNAL_DURATION:
                incoming_pulse = gaussian_ping(
                    t, SONAR_FREQ, SONAR_SIGMA, contact_amp, pulse_center
                )
                signal += incoming_pulse

        result[idx] = {
            'signal': signal.tolist(),
            'time': t.tolist(),
            'has_echo': has_contact,
            'echo_delay': float(contact_delay) if contact_delay is not None else None,
            'echo_amplitude': float(contact_amp) if contact_amp is not None else None,
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

def generate_bomb_shockwave_signals(bomb_coord, my_ships, grid_size,
                                    my_position='left', target_side='enemy',
                                    hit=False, hit_ship_size=None):
    """
    When a bomb goes off, the blast pushes a broadband shockwave through
    the water and every ship in range hears it.

    A MISS is only that shockwave: one low-frequency, broad, featureless
    thump. A HIT adds a second, much higher-frequency burst a fraction of
    a second later — the struck hull rupturing and ringing. That extra
    burst is the whole point: it lands in a different frequency band from
    the blast, so the detector can say "hit" or "miss" on the acoustics
    alone instead of lumping both into one "shockwave" event.

    The ring is louder for a bigger submarine (more steel, more energy
    released), which is how the size of what you hit is recoverable.

    Parameters
    ----------
    bomb_coord : (row, col)
        Where the bomb landed, in the grid it was aimed at.
    my_ships : list of dict
    grid_size : int
    my_position : str
        'left' or 'right' — which half of the unified grid I occupy.
    target_side : str
        'enemy' if the bomb landed on the opponent's grid (I fired it),
        'mine'  if it landed on my own grid (I'm being shot at).
        Without this the defender's distances were computed as if the
        blast were a whole grid away, so their own hull being hit
        registered as a distant event.
    hit : bool
        Did the bomb actually strike a hull?
    hit_ship_size : int or None
        Size of the submarine that was struck.
    """
    t = time_axis()
    bomb_row, bomb_col = bomb_coord

    if target_side == 'mine':
        # Bomb is on my own grid — same frame as my ships, no shift.
        col_offset = 0
    else:
        col_offset = -grid_size if my_position == 'left' else grid_size

    ring_size = hit_ship_size if hit_ship_size else REFERENCE_SHIP_SIZE

    result = {}

    for idx, ship in enumerate(my_ships):
        signal = generate_ocean_noise(len(t))
        has_shockwave = False
        shock_delay = None
        shock_amp = None

        min_dist = float('inf')
        for cell in ship['cells']:
            cr, cc = cell[0], cell[1]
            effective_cc = cc + col_offset
            dr = cr - bomb_row
            dc = effective_cc - bomb_col
            dist = math.sqrt(dr ** 2 + dc ** 2)
            min_dist = min(min_dist, dist)

        MAX_SHOCKWAVE_RANGE = grid_size * 1.5
        if min_dist <= MAX_SHOCKWAVE_RANGE:
            has_shockwave = True
            # Blast front travels one way, from the bomb to us.
            shock_delay = distance_to_delay(min_dist, round_trip=False)
            shock_amp = attenuate(BOMB_AMPLITUDE, min_dist)

            pulse_center = PULSE_ORIGIN_OFFSET + shock_delay

            if pulse_center < SIGNAL_DURATION:
                shockwave = gaussian_ping(
                    t, BOMB_FREQ, BOMB_SIGMA, shock_amp, pulse_center
                )
                signal += shockwave

                # --- the bit that separates a hit from a miss ---
                if hit:
                    ring_amp = attenuate(
                        HULL_AMPLITUDE * target_strength(ring_size), min_dist
                    )
                    ring_center = pulse_center + HULL_RING_LAG
                    if ring_center < SIGNAL_DURATION:
                        signal += gaussian_ping(
                            t, HULL_FREQ, HULL_SIGMA, ring_amp, ring_center
                        )

        result[idx] = {
            'signal': signal.tolist(),
            'time': t.tolist(),
            'has_echo': has_shockwave,
            'echo_delay': float(shock_delay) if shock_delay is not None else None,
            'echo_amplitude': float(shock_amp) if shock_amp is not None else None,
            'blocked': False,
            'blocked_by_size': None,
            'blocker_distance': None,
            'target_size': int(ring_size) if hit else None,
            'target_distance': round(float(min_dist), 2) if has_shockwave else None,
            'was_hit': bool(hit),
        }
    return result


# ============================================================
# Idle Ocean Noise (for continuous display)
# ============================================================

def generate_idle_signals(num_ships):
    """
       Generate pure ocean noise signals for all ships.
    Used when no active event is occurring — gives the oscilloscope
    displays their continuous "listening" animation.

    Parameters
    ----------
    num_ships : int
        Number of ships to generate signals for

    Returns
    -------
    dict
        {ship_index: {'signal': [...], 'time': [...], ...}, ...}
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
