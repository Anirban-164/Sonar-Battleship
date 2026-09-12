"""
game_logic.py — Core game rules and mechanics.

Ship fleet config, placement validation, sonar (angular bearing-based + DSP),
fire processing, and win condition checks.
"""

import math
import random

from game.models import Ship
from game.signal_engine import (
    generate_sonar_echo,
    generate_incoming_sonar_signals,
    find_beam_blocker,
    BEAM_HALF_WIDTH,
)
from game.signal_processor import process_signal


# ============================================================
# Ship config — classic Battleship fleet
# ============================================================
SHIP_FLEET = [
    {'size': 5},
    {'size': 4},
    {'size': 3}
]


# ============================================================
# Placement Validation
# ============================================================

def validate_ship_placement(cells, size, grid_size):
    """
    Validate that a ship's cells are:
    1. Correct count (matches size)
    2. All within the grid
    3. All adjacent in a straight line (horizontal or vertical)
    Returns (is_valid, error_message)
    """
    if len(cells) != size:
        return False, f"Expected {size} cells, got {len(cells)}"

    for r, c in cells:
        if r < 0 or r >= grid_size or c < 0 or c >= grid_size:
            return False, f"Cell ({r},{c}) is out of bounds"

    # Check all cells are in a straight line
    rows = [c[0] for c in cells]
    cols = [c[1] for c in cells]

    if len(set(rows)) == 1:
        # Horizontal — all same row, columns must be consecutive
        sorted_cols = sorted(cols)
        for i in range(1, len(sorted_cols)):
            if sorted_cols[i] != sorted_cols[i-1] + 1:
                return False, "Cells are not adjacent (horizontal)"
    elif len(set(cols)) == 1:
        # Vertical — all same column, rows must be consecutive
        sorted_rows = sorted(rows)
        for i in range(1, len(sorted_rows)):
            if sorted_rows[i] != sorted_rows[i-1] + 1:
                return False, "Cells are not adjacent (vertical)"
    else:
        return False, "Cells are not in a straight line"

    return True, ""


def check_overlap(new_cells, existing_cells):
    """Check if new ship cells overlap with any already-placed cells."""
    existing_set = set(tuple(c) for c in existing_cells)
    for cell in new_cells:
        if tuple(cell) in existing_set:
            return True
    return False


# ============================================================
# Sonar — Angular (bearing-based) detection
# ============================================================

def angular_sonar(origin_row, origin_col, angle_degrees, enemy_player, grid_size,
                  my_position='left', my_player=None):
    """
    Bearing-based sonar: scans from a player's chosen ship cell at a
    given bearing angle. Detects the nearest un-hit enemy ship cell
    within the beam width and returns approximate distance.

    If one of the player's OWN submarines is sitting in the beam closer
    than the enemy, the ping never gets through — it reflects off the
    friendly hull and the scan returns nothing useful.

    origin_row, origin_col: the player's selected undamaged ship cell.
    angle_degrees: 0° = North (up), 90° = East (right), clockwise.
    Beam half-width: BEAM_HALF_WIDTH degrees (shared with signal_engine).
    my_position: 'left' or 'right' — determines the spatial offset
                 between this player's grid and the enemy's grid.
    """
    origin_r = float(origin_row)
    origin_c = float(origin_col)

    # --- Spatial offset for the static facing grid ---
    # Both grids are grid_size wide. In the unified coordinate space:
    #   Player 1 (left):  cols 0 .. (grid_size-1)
    #   Player 2 (right): cols grid_size .. (2*grid_size - 1)
    # So the enemy cells need to be shifted by +grid_size (if I'm left)
    # or -grid_size (if I'm right) relative to my origin.
    if my_position == 'left':
        col_offset = grid_size  # enemy is to my right
    else:
        col_offset = -grid_size  # enemy is to my left

    enemy_ships = Ship.objects.filter(player=enemy_player, is_sunk=False)
    min_distance = float('inf')

    for ship in enemy_ships:
        for cell in ship.cells:
            if list(cell) in ship.hit_cells:
                continue

            cr, cc = cell[0], cell[1]
            # Apply spatial offset to enemy column
            effective_cc = cc + col_offset
            dr = cr - origin_r
            dc = effective_cc - origin_c

            dist = math.sqrt(dr ** 2 + dc ** 2)
            if dist < 0.1:
                min_distance = min(min_distance, dist)
                continue

            # Bearing from origin to this cell (0°=N, 90°=E, clockwise)
            cell_bearing = math.degrees(math.atan2(dc, -dr))
            if cell_bearing < 0:
                cell_bearing += 360

            # Angular difference (handles wraparound)
            diff = abs(cell_bearing - angle_degrees) % 360
            if diff > 180:
                diff = 360 - diff

            if diff <= BEAM_HALF_WIDTH:
                min_distance = min(min_distance, dist)

    # --- Friendly hull in the way? ---
    blocker_dist = None
    blocker_size = None
    if my_player is not None:
        my_ships = [{
            'size': s.size, 'cells': s.cells,
            'hit_cells': s.hit_cells, 'is_sunk': s.is_sunk,
        } for s in Ship.objects.filter(player=my_player)]
        blocker_dist, blocker_size = find_beam_blocker(
            (origin_row, origin_col), angle_degrees, my_ships
        )

    if blocker_dist is not None and (min_distance == float('inf')
                                     or blocker_dist < min_distance):
        return {
            "distance": -1,
            "contact": False,
            "blocked": True,
            "blocked_by_size": blocker_size,
            "blocker_distance": round(blocker_dist, 1),
            "bearing": angle_degrees,
            "origin": [origin_row, origin_col],
        }

    if min_distance == float('inf'):
        return {
            "distance": -1, "contact": False, "blocked": False,
            "bearing": angle_degrees,
            "origin": [origin_row, origin_col]
        }

    # Add slight noise to distance (±0.5 cells)
    noisy_distance = min_distance + random.uniform(-0.5, 0.5)
    return {
        "distance": round(max(0.1, noisy_distance), 1),
        "contact": True,
        "blocked": False,
        "bearing": angle_degrees,
        "origin": [origin_row, origin_col]
    }


def dsp_sonar(origin_row, origin_col, angle_degrees, enemy_player,
             my_player, grid_size, my_position='left'):
    """
    DSP-driven sonar: generates a real acoustic signal, processes it
    through FFT + matched filter, and returns what the DSP extracts.
    Unlike angular_sonar(), this does NOT peek at the true distance.
    """
    origin = [origin_row, origin_col]

    # get my ships as dicts for the signal engine
    my_ships = [{
        'size': s.size, 'cells': s.cells,
        'hit_cells': s.hit_cells, 'is_sunk': s.is_sunk,
    } for s in Ship.objects.filter(player=my_player)]

    # get enemy ships (signal engine needs them to place echoes)
    enemy_ships = [{
        'cells': s.cells, 'hit_cells': s.hit_cells, 'is_sunk': s.is_sunk,
    } for s in Ship.objects.filter(player=enemy_player)]

    # generate the raw signal (physics sim — echo is buried in noise)
    raw_signals = generate_sonar_echo(
        origin,
        angle_degrees,
        my_ships,
        enemy_ships,
        grid_size,
        my_position
    )

    # Which hydrophone do we read? The one on the boat that actually
    # transmitted. Previously this compared only each ship's FIRST cell
    # to the origin, so picking an origin near the tail of a long
    # submarine could hand us a different boat's (weaker) recording.
    best_ship_idx = 0
    best_dist = float('inf')
    for idx, ship in enumerate(my_ships):
        for cell in ship['cells']:
            if cell[0] == origin_row and cell[1] == origin_col:
                best_ship_idx = idx
                best_dist = 0.0
                break
            d = math.sqrt((cell[0] - origin_row) ** 2 + (cell[1] - origin_col) ** 2)
            if d < best_dist:
                best_dist = d
                best_ship_idx = idx
        if best_dist == 0.0:
            break

    origin_signal = raw_signals[best_ship_idx]['signal']
    echo_meta = raw_signals[best_ship_idx]

    # run the DSP pipeline
    dsp_result = process_signal(origin_signal)

    base = {
        'bearing': angle_degrees,
        'origin': origin,
        'confidence': dsp_result['confidence'],
        'snr': dsp_result['snr'],
        'dsp_driven': True,
    }

    # The ping bounced off one of our own boats — the beam never reached
    # the enemy, so there is nothing to report about them. We still spent
    # the turn, which is the cost of a badly chosen bearing.
    if echo_meta.get('blocked'):
        base.update({
            'distance': -1,
            'contact': False,
            'blocked': True,
            'blocked_by_size': echo_meta.get('blocked_by_size'),
            'blocker_distance': echo_meta.get('blocker_distance'),
            'estimated_size': None,
        })
        return base

    # return what the DSP found (NOT the true distance)
    if dsp_result['detected'] and dsp_result['signal_type'] == 'sonar':
        base.update({
            'distance': dsp_result['estimated_distance'],
            'contact': True,
            'blocked': False,
            'estimated_size': dsp_result['estimated_size'],
        })
    else:
        base.update({
            'distance': -1,
            'contact': False,
            'blocked': False,
            'estimated_size': None,
        })
    return base


# ============================================================
# Passive sonar — counter-detection
# ============================================================
#
# Active sonar is loud. A real submarine that pings announces itself to
# everything in the water, which is exactly why boats prefer to listen.
# The signal engine already put the enemy's outgoing pulse onto our
# hydrophones (generate_incoming_sonar_signals) — it was only ever drawn
# as a waveform and thrown away. Below, it becomes information.
#
# One hydrophone can measure how far away a transmitter is (from the
# arrival delay) but not which direction it lies in. Several hydrophones
# at known positions, each with its own range, pin the source down by
# multilateration: the point whose distance to every receiver best
# matches what each of them measured. So a fleet that still has two or
# three boats alive can work out a bearing; a fleet down to one boat
# only learns how far away the noise was.


def _to_unified(row, col, grid_size, position):
    """
    Put a cell into the shared coordinate space both fleets live in:
    the left player holds columns 0..grid_size-1, the right player holds
    grid_size..2*grid_size-1. Rows are already common.
    """
    return (float(row), float(col) + (0.0 if position == 'left' else float(grid_size)))


def _multilaterate(receivers, grid_size, source_position):
    """
    Find the cell in the transmitter's half of the board whose distance to
    each listening hydrophone best matches that hydrophone's measured
    range (least squares).

    A plain search over the 100 candidate cells rather than an algebraic
    solve: the search space is tiny, it cannot diverge the way an
    iterative solver can on noisy ranges, and it can only ever return a
    cell that really exists on the board.

    receivers: [((unified_row, unified_col), measured_range), ...]
    Returns (residual, unified_point, [row, col] in the source's own grid)
    """
    best = None
    for r in range(grid_size):
        for c in range(grid_size):
            ur, uc = _to_unified(r, c, grid_size, source_position)
            residual = 0.0
            for (pr, pc), measured in receivers:
                d = math.hypot(ur - pr, uc - pc)
                residual += (d - measured) ** 2
            if best is None or residual < best[0]:
                best = (residual, (ur, uc), [r, c])
    return best


def counter_detect(enemy_origin, angle_degrees, listener, grid_size,
                   listener_position):
    """
    Work out what the player being pinged hears.

    Returns a report meant only for the listener — never for the player
    who transmitted, who in reality has no way of knowing whether anyone
    was listening.

    {
      'detected':      bool,
      'range':         cells from the primary hydrophone to the transmitter,
      'bearing':       degrees (0 = North) or None if it can't be fixed,
      'confidence':    0..1 from the strongest hydrophone,
      'hydrophones':   how many of our boats heard it,
      'listener_cell': the primary hydrophone's cell, in our own grid,
      'fix_quality':   'fix' (bearing + range) or 'range_only',
    }
    """
    my_ships = [{
        'size': s.size, 'cells': s.cells,
        'hit_cells': s.hit_cells, 'is_sunk': s.is_sunk,
    } for s in Ship.objects.filter(player=listener, is_sunk=False)]

    return counter_detect_from_ships(
        enemy_origin, angle_degrees, my_ships, grid_size, listener_position
    )


def counter_detect_from_ships(enemy_origin, angle_degrees, my_ships, grid_size,
                              listener_position):
    """
    The database-free half of counter_detect(), so the acoustics can be
    exercised without a Django connection (see game/dsp_harness.py).
    """
    if not my_ships:
        return {'detected': False, 'hydrophones': 0}

    # The same pulse the attacker transmitted, as it reaches each of our
    # boats — noise, attenuation and all.
    incoming = generate_incoming_sonar_signals(
        enemy_origin, angle_degrees, my_ships, grid_size, listener_position
    )

    receivers = []       # [(unified position, measured range)]
    best_conf = 0.0
    primary = None       # (confidence, range, unified pos, local cell)

    for idx, data in incoming.items():
        ship = my_ships[idx]
        out = process_signal(data['signal'])

        if not (out['detected'] and out['signal_type'] == 'sonar'):
            continue

        # The enemy's ping is a DIRECT arrival, not an echo off something,
        # so the one-way reading is the correct hypothesis here.
        measured = out['estimated_distance_direct']
        if measured is None:
            continue

        # Treat the boat as a single hydrophone at the middle of its hull.
        cells = ship['cells']
        mid = cells[len(cells) // 2]
        unified = _to_unified(mid[0], mid[1], grid_size, listener_position)

        receivers.append((unified, measured))

        if out['confidence'] >= best_conf:
            best_conf = out['confidence']
            primary = (out['confidence'], measured, unified, [mid[0], mid[1]])

    if not receivers or primary is None:
        return {'detected': False, 'hydrophones': 0}

    _conf, primary_range, primary_pos, primary_cell = primary
    source_position = 'right' if listener_position == 'left' else 'left'

    report = {
        'detected': True,
        'range': round(primary_range, 1),
        'confidence': round(best_conf, 4),
        'hydrophones': len(receivers),
        'listener_cell': primary_cell,
        'bearing': None,
        'fix_quality': 'range_only',
    }

    # A single hydrophone gives a range circle and nothing more — there
    # is no direction information in one arrival time.
    if len(receivers) < 2:
        return report

    residual, fix_point, fix_cell = _multilaterate(
        receivers, grid_size, source_position
    )

    # Bearing from the boat that heard it best to wherever the fix landed.
    dr = fix_point[0] - primary_pos[0]
    dc = fix_point[1] - primary_pos[1]
    if abs(dr) < 1e-9 and abs(dc) < 1e-9:
        return report

    brg = math.degrees(math.atan2(dc, -dr))
    if brg < 0:
        brg += 360

    # How much to trust the fix. The residual is the sum of squared
    # mismatches between each hydrophone's measured range and the chosen
    # point, so its RMS is roughly how many cells the measurements
    # disagree by. Reported as a search radius rather than a single cell:
    # the fix is an estimate from noisy arrivals, and presenting it as a
    # pinpoint would overstate what the acoustics actually support.
    rms = math.sqrt(residual / max(1, len(receivers) - 1))
    radius = int(max(1, min(5, round(rms + 1))))

    report['bearing'] = round(brg, 1)
    report['range'] = round(math.hypot(dr, dc), 1)
    report['fix_quality'] = 'fix'
    report['fix_residual'] = round(float(residual), 2)
    report['fix_cell'] = fix_cell          # best-guess cell, enemy's own grid
    report['fix_radius'] = radius          # +/- cells of search area
    return report


# ============================================================
# Fire — Direct cell lookup
# ============================================================

def process_fire(target_row, target_col, enemy_player):
    """
    Fire logic: direct cell lookup.

    The returned dict now carries `ship_size`, because the acoustics
    depend on it — a bomb that breaks a 5-cell boat rings louder and
    longer than one that clips a 3-cell boat, and the signal engine needs
    to know which it was in order to render the hit signature.

    Returns {"hit": bool, "ship_name": str|None, "sunk": bool,
             "ship_size": int|None, "already_hit": bool}
    """
    enemy_ships = Ship.objects.filter(player=enemy_player)

    for ship in enemy_ships:
        for cell in ship.cells:
            if cell[0] == target_row and cell[1] == target_col:
                # Check if already hit — a second bomb into an existing
                # hole is water, not hull. No new damage, no hull ring.
                if [target_row, target_col] in ship.hit_cells:
                    return {
                        "hit": False, "already_hit": True,
                        "ship_name": None, "sunk": False, "ship_size": None,
                    }

                # Record the hit
                ship.hit_cells = ship.hit_cells + [[target_row, target_col]]
                # Check if sunk (all cells hit)
                if len(ship.hit_cells) >= ship.size:
                    ship.is_sunk = True
                ship.save()

                return {
                    "hit": True,
                    "already_hit": False,
                    "ship_name": "Submarine",
                    "sunk": ship.is_sunk,
                    "ship_size": int(ship.size),
                }

    return {"hit": False, "already_hit": False, "ship_name": None,
            "sunk": False, "ship_size": None}


# ============================================================
# Win Condition
# ============================================================

def check_win(enemy_player):
    """Check if all of enemy's ships are sunk."""
    return not Ship.objects.filter(player=enemy_player, is_sunk=False).exists()
