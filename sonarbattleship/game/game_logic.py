"""
game_logic.py — Core game rules and mechanics.

Ship fleet config, placement validation, sonar (angular bearing-based),
fire processing, and win condition checks.
"""

import math
import random

from game.models import Ship


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

def angular_sonar(origin_row, origin_col, angle_degrees, enemy_player, grid_size, my_position='left'):
    """
    Bearing-based sonar: scans from a player's chosen ship cell at a
    given bearing angle. Detects the nearest un-hit enemy ship cell
    within the beam width and returns approximate distance.

    origin_row, origin_col: the player's selected undamaged ship cell.
    angle_degrees: 0° = North (up), 90° = East (right), clockwise.
    Beam half-width: 12°.
    my_position: 'left' or 'right' — determines the spatial offset
                 between this player's grid and the enemy's grid.
    """
    origin_r = float(origin_row)
    origin_c = float(origin_col)

    BEAM_HALF_WIDTH = 12  # degrees

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

    if min_distance == float('inf'):
        return {
            "distance": -1, "contact": False, "bearing": angle_degrees,
            "origin": [origin_row, origin_col]
        }

    # Add slight noise to distance (±0.5 cells)
    noisy_distance = min_distance + random.uniform(-0.5, 0.5)
    return {
        "distance": round(max(0.1, noisy_distance), 1),
        "contact": True,
        "bearing": angle_degrees,
        "origin": [origin_row, origin_col]
    }


# ============================================================
# Fire — Direct cell lookup
# ============================================================

def process_fire(target_row, target_col, enemy_player):
    """
    Week 2 fire logic: direct cell lookup.
    Returns {"hit": bool, "ship_name": str|None, "sunk": bool}
    """
    enemy_ships = Ship.objects.filter(player=enemy_player)

    for ship in enemy_ships:
        for cell in ship.cells:
            if cell[0] == target_row and cell[1] == target_col:
                # Check if already hit
                if [target_row, target_col] in ship.hit_cells:
                    return {"hit": False, "already_hit": True, "ship_name": None, "sunk": False}

                # Record the hit
                ship.hit_cells = ship.hit_cells + [[target_row, target_col]]
                # Check if sunk (all cells hit)
                if len(ship.hit_cells) >= ship.size:
                    ship.is_sunk = True
                ship.save()

                return {
                    "hit": True,
                    "ship_name": "Submarine",
                    "sunk": ship.is_sunk
                }

    return {"hit": False, "ship_name": None, "sunk": False}


# ============================================================
# Win Condition
# ============================================================

def check_win(enemy_player):
    """Check if all of enemy's ships are sunk."""
    return not Ship.objects.filter(player=enemy_player, is_sunk=False).exists()
