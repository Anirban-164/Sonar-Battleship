import numpy as np
import math

#------------------------------------------------------------
# Constants
#------------------------------------------------------------

SAMPLE_RATE = 200 # samples/sec
SIGNAL_DURATION = 3.0 # seconds of signal per snapshot
NUM_SAMPLES = int(SAMPLE_RATE * SIGNAL_DURATION)

# Sonar pulse
SONAR_FREQ = 5.0 # carrier
SONAR_SIGMA = 0.08 # Gaussian width (sec)
SONAR_AMPLITUDE = 1.0 # Peak amplitude (b4 attenuation)

# fire shockwave
BOMB_FREQ = 2.0 # lower, broader
BOMB_SIGMA = 0.15 # Wider Gaussian
BOMB_AMPLITUDE = 0.7

# Environment
NOISE_LEVEL = 0.15 # sigma of AWGN
ATTENUATION_ALPHA = 0.3 # distance decay coefficient
DELAY_PER_CELL = 0.15 # sec of delay per grid cell distance


########### core signal generators ##############
def time_axis():
    """ generates the time axis for a signal snapshot """
    return np.linspace(0, SIGNAL_DURATION, NUM_SAMPLES, endpoint=False)


def gaussian_ping(t, freq, sigma, amp, center):
    """
    Generates a Gaussian-windowed sine pulse (a 'ping').
    Formula: p(t) = amp * exp(-(t - center)^2 / (2 * sigma^2)) * sin(2 * pi * freq * t)
    The Gaussian part makes it a short burst rather than an infinite wave,
    useful for matched filtering later.
    """

    expo = np.exp(-0.5 * (((t-center)/sigma)**2))
    return amp * expo * np.sin(2 * np.pi * freq * t)


def attenuate(amp, dist):
    """
    Reduces amplitude based on distance.
    Formula: A_received = A_source / (1 + alpha * dist)
    Simulates sound energy loss as it travels through water.
    """
    return amp / (1 + ATTENUATION_ALPHA * dist)


def distance_to_delay(dist):
    """
    Maps grid distance to a time delay in seconds.
    Used to shift the echo on the time axis so we can calculate distance later.
    """
    return dist * DELAY_PER_CELL

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


################# sonar  ping ################
def _in_beam(origin, target, angle, half_width=10):
    """
    Returns true if target is in beam centered at angle
    """
    ori_r, ori_c = origin
    tr, tc = target
    dr = tr - ori_r
    dc = tc - ori_c
    
    if dr == 0 and dc == 0:
        return True

    cell_bearing = math.degrees(math.atan2(dc, -dr))
    if cell_bearing < 0:
        cell_bearing += 360
    diff = abs(cell_bearing - angle) % 360
    if diff > 180:
        diff = 360 - diff
    if diff <= half_width:
        return True
    return False


def generate_sonar_echo(origin, angle_deg, my_ships, enemy_ships, grid_size, side='left'):
    """
    Generate the signals received by each of the player's ships
    after a sonar ping.
    The ping travels outward from the origin ship cell. If it hits
    an enemy ship cell within the beam, an echo returns. Each of the
    player's ships "hears" this echo, with amplitude depending on
    distance from the origin.
    The originating ship gets the strongest signal. Other ships
    get attenuated versions based on their distance from the origin.
    Parameters
    ----------
    origin_row, origin_col : int
        The ship cell the player selected as sonar origin
    angle_deg : float
        Bearing angle (0°=North, clockwise)
    my_ships : list of dict
        Player's own ships: [{'size': int, 'cells': [[r,c],...], ...}, ...]
    enemy_ships : list of dict
        Enemy ships (with cells, hit_cells, is_sunk)
    grid_size : int
        Grid dimension
    my_position : str
        'left' or 'right'
    Returns
    -------
    dict
        {
            ship_index: {
                'signal': [float, ...],   # 600 samples
                'time': [float, ...],     # 600 time values
                'has_echo': bool,
                'echo_delay': float or None,
                'echo_amplitude': float or None
            },
            ...
        }
    """

    t = time_axis()
    
    BEAM_WIDTH = 20
    ori_r, ori_c = origin
    col_offset = grid_size if side == 'left' else -grid_size

    min_enemy_dist = float('inf')
    for ship in enemy_ships:
        if ship.get('is_sunk', False) == True:
            continue

        for cell in ship.get('cells'):
            # if cell in ship.get('hit_cells', []):
            #     continue

            cr, cc = cell[0], cell[1]
            eff_cc = cc + col_offset #effective col
            dr = cr - ori_r
            dc = eff_cc - ori_c
            dist = math.sqrt(dr ** 2 + dc ** 2)
            if dist < 0.1:
                min_enemy_dist = 0.1
                continue

            # Check if within beam
            if _in_beam(origin, (cr, eff_cc), angle_deg, BEAM_WIDTH/2):
                min_enemy_dist = min(min_enemy_dist, dist)

    has_echo = min_enemy_dist < float('inf')

    # generate signal for each of the player's ships
    result = {}
    for idx, ship in enumerate(my_ships):
        # Distance from this ship's first cell to the sonar origin
        ship_cell = ship['cells'][0]
        dist_to_origin = math.sqrt((ship_cell[0] - ori_r) ** 2 + (ship_cell[1] - ori_c) ** 2)

        # ocean noise (base signal)
        signal = generate_ocean_noise(len(t))
        echo_delay = None
        echo_amp = None
        if has_echo:
            # Echo delay based on distance to nearest enemy
            echo_delay = distance_to_delay(min_enemy_dist)
            base_amp = attenuate(SONAR_AMPLITUDE, min_enemy_dist) # for the ship that fired the signal
            ship_attenuation = attenuate(1.0, dist_to_origin) # for the rest of the ships --> further attenuated by how far this ship is from origin ship
            echo_amp = base_amp * ship_attenuation
            
            pulse_center = 0.5 + echo_delay  # 0.5s initial offset
            if pulse_center < SIGNAL_DURATION:
                echo = gaussian_ping(t, SONAR_FREQ, SONAR_SIGMA, echo_amp, pulse_center)
                signal += echo
        result[idx] = {
            'signal': signal.tolist(),
            'time': t.tolist(),
            'has_echo': has_echo,
            'echo_delay': float(echo_delay) if echo_delay else None,
            'echo_amplitude': float(echo_amp) if echo_amp else None,
        }
    return result
   
            
    
# ============================================================
# Scenario 2: Enemy Sonar passes near our ships
# ============================================================
def generate_incoming_sonar_signals(enemy_origin,angle_deg,my_ships,grid_size,my_position='left'):
    """
    When the enemy fires sonar, the ping pulse travels through the water. Each of our ships in or near the beam path picks up the incoming signal. The nearest ship gets the highest amplitude bump; farther ships get weaker signals.

    This is a DIRECT arrival (not an echo), so there's no round-trip — the delay is one-way: d / v_sound.

    Parameters
    ----------
    enemy_origin_row, enemy_origin_col : int
        Where the enemy's sonar originated
    angle_deg : float
        Enemy's sonar bearing
    my_ships : list of dict
        Our ships
    grid_size : int
    my_position : str

    Returns
    -------
    dict
        Same structure as generate_sonar_echo_signals
    """
    t = time_axis()
    enemy_origin_row, enemy_origin_col = enemy_origin
    col_offset = -grid_size
    if my_position != 'left':
        col_offset = grid_size
        # ^ Reversed: from the enemy's perspective, we're on the other side

    result = {}
    for idx,ship in enumerate(my_ships):
        signal = generate_ocean_noise(len(t))
        has_contact = False
        contact_delay = None
        contact_amp = None

        for cell in ship['cells']:
            # if cell in ship.get('hit_cells',[]):
            #     continue

            # Distance from enemy origin to this cell
            # (account for the grid offset)
            cr,cc = cell[0],cell[1]
            effective_cc = cc + col_offset
            dr = cr - enemy_origin_row
            dc = effective_cc - enemy_origin_col
            dist = math.sqrt(dr ** 2 + dc ** 2)
            # Check if this cell is within the enemy's beam
            BEAM_HALF_WIDTH = 10
           
            if _in_beam(enemy_origin, (cr, effective_cc), angle_deg, half_width=BEAM_HALF_WIDTH * 2):
                # One-way delay (not round-trip)
                delay = distance_to_delay(dist)/2.0
                amp = attenuate(SONAR_AMPLITUDE*0.8,dist)

                if not has_contact or amp > contact_amp:
                    has_contact = True
                    contact_delay = delay
                    contact_amp = amp

        if has_contact and contact_delay is not None:
            pulse_center = 0.3 + contact_delay
            if pulse_center < SIGNAL_DURATION:
                incoming_pulse = gaussian_ping(t,SONAR_FREQ,SONAR_SIGMA,contact_amp,pulse_center)
                signal += incoming_pulse

        result[idx] = {
            'signal' : signal.tolist(),
            'time':t.tolist(),
            'has_echo': has_contact,
            'echo_delay': float(contact_delay) if contact_delay else None,
            'echo_amplitude': float(contact_amp) if contact_amp else None,
        }
    return result



# ============================================================
# Scenario 3: Fire/Bomb Shockwave
# ============================================================

def generate_bomb_shockwave_signals(bomb_coord,my_ships,grid_size,my_position='left'):
    """
    When the enemy fires at a cell (hit or miss), the explosion
    generates a broadband shockwave that propagates through the
    water. All ships within range detect it.

    Key differences from sonar:
    - Lower frequency, wider pulse (less precise timing information)
    - No known template (the player doesn't know the exact pulse
      shape, so matched filtering in Week 4 is less effective)
    - Gives SOME distance info, but less accurate than sonar

    This creates the gameplay asymmetry: sonar costs a turn but gives
    precise distance; bomb impacts are "free" info but imprecise.

    Parameters
    ----------
    bomb_row, bomb_col : int
        Where the bomb landed
    my_ships : list of dict
    grid_size : int
    my_position : str

    Returns
    -------
    dict
        Same structure as above
    """
    t = time_axis()
    bomb_row, bomb_col = bomb_coord
    col_offset = -grid_size
    if my_position != 'left':
        col_offset = grid_size
    

    result = {}

    for idx, ship in enumerate(my_ships):
        signal = generate_ocean_noise(len(t))
        has_shockwave = False
        shock_delay = None
        shock_amp = None

        min_dist = float('inf')
        for cell in ship['cells']:
            cr,cc = cell[0],cell[1]
            effective_cc = cc + col_offset
            dr = cr - bomb_row
            dc = effective_cc - bomb_col
            dist = math.sqrt(dr ** 2 + dc ** 2)
            min_dist = min(min_dist,dist)

        MAX_SHOCKWAVE_RANGE = grid_size * 1.5
        if min_dist <= MAX_SHOCKWAVE_RANGE:
            has_shockwave = True
            shock_delay = distance_to_delay(min_dist)/2.0
            shock_amp = attenuate(BOMB_AMPLITUDE,min_dist)

            pulse_center = 0.4 + shock_delay

            if pulse_center < SIGNAL_DURATION:
                shockwave = gaussian_ping(t,BOMB_FREQ,BOMB_SIGMA,shock_amp,pulse_center)
                signal += shockwave

        result[idx] = {
            'signal':signal.tolist(),
            'time':t.tolist(),
            'has_echo':has_shockwave,
            'echo_delay':float(shock_delay) if shock_delay else None,
            'echo_amplitude': float(shock_amp) if shock_amp else None
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
        result[idx] ={
            'signal':signal.tolist(),
            'time':t.tolist(),
            'has_echo':False,
            'echo_delay':None,
            'echo_amplitude': None,
        }
    return result

