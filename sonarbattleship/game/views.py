import json
import math
import random
import string
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

from game.models import Room, Player, Ship, Action


# ============================================================
# Ship config — classic Battleship fleet
# ============================================================
SHIP_FLEET = [
    {'size': 5},
    {'size': 4},
    {'size': 3}
]

GRID_SIZE = 15  # 15x15 grid, matches DB default


# ============================================================
# Helper functions
# ============================================================

def _generate_room_code():
    """Generate a unique 6-character room code."""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not Room.objects.filter(code=code).exists():
            return code


def _get_session_key(request):
    """Ensure the request has a session and return its key."""
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def _get_player(room, session_key):
    """Get the Player object for this session in this room, or None."""
    try:
        return Player.objects.get(room=room, session_key=session_key)
    except Player.DoesNotExist:
        return None


def _validate_ship_placement(cells, size, grid_size):
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


def _check_overlap(new_cells, existing_ships):
    """Check if new ship cells overlap with any already-placed ship."""
    existing_cells = set()
    for ship in existing_ships:
        for cell in ship.cells:
            existing_cells.add(tuple(cell))

    for cell in new_cells:
        if tuple(cell) in existing_cells:
            return True
    return False


def _angular_sonar(origin_row, origin_col, angle_degrees, enemy_player, grid_size):
    """
    Bearing-based sonar: scans from a player's chosen ship cell at a
    given bearing angle. Detects the nearest un-hit enemy ship cell
    within the beam width and returns approximate distance.

    origin_row, origin_col: the player's selected undamaged ship cell.
    angle_degrees: 0° = North (up), 90° = East (right), clockwise.
    Beam half-width: 12°.
    """
    origin_r = float(origin_row)
    origin_c = float(origin_col)

    BEAM_HALF_WIDTH = 12  # degrees

    enemy_ships = Ship.objects.filter(player=enemy_player, is_sunk=False)
    min_distance = float('inf')

    for ship in enemy_ships:
        for cell in ship.cells:
            if list(cell) in ship.hit_cells:
                continue

            cr, cc = cell[0], cell[1]
            dr = cr - origin_r
            dc = cc - origin_c

            dist = math.sqrt(dr ** 2 + dc ** 2)
            if dist < 0.1:
                # Cell is essentially at origin — always detected
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


def _process_fire(target_row, target_col, enemy_player):
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


def _check_win(enemy_player):
    """Check if all of enemy's ships are sunk."""
    return not Ship.objects.filter(player=enemy_player, is_sunk=False).exists()


def _get_enemy_player(room, current_player):
    """Get the other player in the room."""
    return Player.objects.filter(room=room).exclude(id=current_player.id).first()


# ============================================================
# Page views
# ============================================================

def home(request):
    """Landing page — create or join a room."""
    _get_session_key(request)  # ensure session exists
    return render(request, 'game/home.html')


def room(request, room_code):
    """Main game page for a specific room."""
    room_obj = get_object_or_404(Room, code=room_code.upper())
    session_key = _get_session_key(request)
    player = _get_player(room_obj, session_key)

    if not player:
        # Player hasn't joined this room yet — redirect to home
        return render(request, 'game/home.html', {
            'error': 'You are not in this room. Please join using the room code.'
        })

    return render(request, 'game/room.html', {
        'room_code': room_obj.code,
        'player_name': player.name,
        'grid_size': room_obj.grid_size,
        'ship_fleet': json.dumps(SHIP_FLEET),
    })


# ============================================================
# API views
# ============================================================

@csrf_exempt
@require_POST
def api_create_room(request):
    """Create a new room, add the creator as Player 1."""
    session_key = _get_session_key(request)
    data = json.loads(request.body)
    player_name = data.get('name', 'Player 1')

    room = Room.objects.create(
        code=_generate_room_code(),
        status='waiting',
    )
    Player.objects.create(
        room=room,
        session_key=session_key,
        name=player_name,
    )

    return JsonResponse({'room_code': room.code})


@csrf_exempt
@require_POST
def api_join_room(request):
    """Join an existing room using a room code."""
    session_key = _get_session_key(request)
    data = json.loads(request.body)
    room_code = data.get('code', '').upper().strip()
    player_name = data.get('name', 'Player 2')

    try:
        room = Room.objects.get(code=room_code)
    except Room.DoesNotExist:
        return JsonResponse({'error': 'Room not found'}, status=404)

    # Check if this session is already in the room
    existing = _get_player(room, session_key)
    if existing:
        return JsonResponse({'room_code': room.code})

    # Check if room is full
    if room.players.count() >= 2:
        return JsonResponse({'error': 'Room is full'}, status=400)

    Player.objects.create(
        room=room,
        session_key=session_key,
        name=player_name,
    )

    # If 2 players now, move to placement phase
    if room.players.count() == 2:
        room.status = 'placement'
        room.save()

    return JsonResponse({'room_code': room.code})


@require_GET
def api_room_state(request, room_code):
    """
    Polled by the frontend every ~2-3 seconds.
    Returns the full game state visible to the requesting player.
    """
    room = get_object_or_404(Room, code=room_code.upper())
    session_key = _get_session_key(request)
    me = _get_player(room, session_key)

    if not me:
        return JsonResponse({'error': 'Not in this room'}, status=403)

    enemy = _get_enemy_player(room, me)

    # Build player list
    players_data = []
    for p in room.players.all():
        players_data.append({
            'id': str(p.id),
            'name': p.name,
            'is_me': p.id == me.id,
            'ships_placed': p.ships_placed,
        })

    # My ships (full detail)
    my_ships = []
    for s in Ship.objects.filter(player=me):
        my_ships.append({
            'name': f"Submarine ({s.size})",
            'size': s.size,
            'cells': s.cells,
            'hit_cells': s.hit_cells,
            'is_sunk': s.is_sunk,
        })

    # Enemy ships — only reveal sunk ships and hit cells, not positions
    enemy_ships = []
    if enemy:
        for s in Ship.objects.filter(player=enemy):
            ship_data = {
                'name': f"Submarine ({s.size})" if s.is_sunk else '???',
                'size': s.size if s.is_sunk else None,
                'cells': s.cells if s.is_sunk else None,
                'hit_cells': s.hit_cells,  # show where you've hit
                'is_sunk': s.is_sunk,
            }
            enemy_ships.append(ship_data)

    # Action history (this player's actions and results)
    my_actions = []
    for a in Action.objects.filter(room=room, player=me).order_by('-created_at')[:20]:
        action_data = {
            'type': a.action_type,
            'result': a.result,
        }
        if a.action_type == 'sonar':
            # bearing stored in target_col, origin in result
            action_data['bearing'] = a.target_col
            if a.result and 'origin' in a.result:
                action_data['origin'] = a.result['origin']
        else:
            action_data['target'] = [a.target_row, a.target_col]
        my_actions.append(action_data)

    # Enemy's actions against me (so I can see where they fired on my grid)
    enemy_actions = []
    if enemy:
        for a in Action.objects.filter(room=room, player=enemy).order_by('-created_at')[:20]:
            action_data = {
                'type': a.action_type,
                'result': a.result,
            }
            if a.action_type == 'sonar':
                action_data['bearing'] = a.target_col
                if a.result and 'origin' in a.result:
                    action_data['origin'] = a.result['origin']
            else:
                action_data['target'] = [a.target_row, a.target_col]
            enemy_actions.append(action_data)

    return JsonResponse({
        'status': room.status,
        'grid_size': room.grid_size,
        'current_turn': str(room.current_turn_id) if room.current_turn_id else None,
        'my_id': str(me.id),
        'is_my_turn': room.current_turn_id == me.id,
        'winner': str(room.winner_id) if room.winner_id else None,
        'players': players_data,
        'my_ships': my_ships,
        'enemy_ships': enemy_ships,
        'my_actions': my_actions,
        'enemy_actions': enemy_actions,
        'ship_fleet': SHIP_FLEET,
    })


@csrf_exempt
@require_POST
def api_place_ships(request, room_code):
    """
    Player submits all their ship placements at once.
    Expects JSON: {"ships": [{"name": "Carrier", "cells": [[0,0],[0,1],...], "orientation": "H"}, ...]}
    """
    room = get_object_or_404(Room, code=room_code.upper())
    session_key = _get_session_key(request)
    me = _get_player(room, session_key)

    if not me:
        return JsonResponse({'error': 'Not in this room'}, status=403)

    if room.status != 'placement':
        return JsonResponse({'error': 'Not in placement phase'}, status=400)

    if me.ships_placed:
        return JsonResponse({'error': 'You already placed your ships'}, status=400)

    data = json.loads(request.body)
    ships_data = data.get('ships', [])

    # Validate fleet composition
    expected_sizes = sorted([s['size'] for s in SHIP_FLEET])
    submitted_sizes = sorted([s['size'] for s in ships_data])
    if expected_sizes != submitted_sizes:
        return JsonResponse({
            'error': f'Invalid fleet sizes. Expected: {expected_sizes}'
        }, status=400)

    # Validate and create each ship
    created_ships = []
    all_cells = []  # track all placed cells for overlap checking

    for ship_data in ships_data:
        cells = [list(c) for c in ship_data['cells']]
        size = ship_data['size']

        # Validate placement
        valid, error = _validate_ship_placement(cells, size, room.grid_size)
        if not valid:
            # Rollback any created ships
            Ship.objects.filter(id__in=[s.id for s in created_ships]).delete()
            return JsonResponse({
                'error': f"Ship of size {size}: {error}"
            }, status=400)

        # Check overlap with already-placed ships in this submission
        for cell in cells:
            if tuple(cell) in [(c[0], c[1]) for c in all_cells]:
                Ship.objects.filter(id__in=[s.id for s in created_ships]).delete()
                return JsonResponse({
                    'error': f"Ship of size {size} overlaps with another ship"
                }, status=400)
            all_cells.append(cell)

        ship = Ship.objects.create(
            player=me,
            size=size,
            cells=cells,
            orientation=ship_data.get('orientation', 'H'),
        )
        created_ships.append(ship)

    # Mark player as having placed ships
    me.ships_placed = True
    me.save()

    # Check if both players have placed — if so, start the game
    enemy = _get_enemy_player(room, me)
    if enemy and enemy.ships_placed:
        # Pick a random starting player
        first_player = random.choice([me, enemy])
        room.status = 'in_progress'
        room.current_turn = first_player
        room.save()

    return JsonResponse({'success': True})


@csrf_exempt
@require_POST
def api_action(request, room_code):
    """
    Process a turn action.
    Sonar expects: {"action_type": "sonar", "angle": int}  (0-359 degrees)
    Fire expects:  {"action_type": "fire", "target_row": int, "target_col": int}
    """
    room = get_object_or_404(Room, code=room_code.upper())
    session_key = _get_session_key(request)
    me = _get_player(room, session_key)

    if not me:
        return JsonResponse({'error': 'Not in this room'}, status=403)

    if room.status != 'in_progress':
        return JsonResponse({'error': 'Game is not in progress'}, status=400)

    if room.current_turn_id != me.id:
        return JsonResponse({'error': 'Not your turn'}, status=400)

    data = json.loads(request.body)
    action_type = data.get('action_type')

    if action_type not in ('sonar', 'fire'):
        return JsonResponse({'error': 'Invalid action type'}, status=400)

    enemy = _get_enemy_player(room, me)
    if not enemy:
        return JsonResponse({'error': 'No opponent'}, status=400)

    if action_type == 'sonar':
        angle = data.get('angle', 0)
        origin_row = data.get('origin_row')
        origin_col = data.get('origin_col')

        if not (0 <= angle < 360):
            return JsonResponse({'error': 'Angle must be between 0 and 359'}, status=400)

        if origin_row is None or origin_col is None:
            return JsonResponse({'error': 'Select an undamaged ship cell as sonar origin'}, status=400)

        # Validate origin cell belongs to player's own undamaged ship cell
        my_ships = Ship.objects.filter(player=me, is_sunk=False)
        origin_valid = False
        for ship in my_ships:
            for cell in ship.cells:
                if cell[0] == origin_row and cell[1] == origin_col:
                    if [origin_row, origin_col] not in ship.hit_cells:
                        origin_valid = True
                        break
            if origin_valid:
                break

        if not origin_valid:
            return JsonResponse({'error': 'Origin must be an undamaged cell of your own ship'}, status=400)

        result = _angular_sonar(origin_row, origin_col, angle, enemy, room.grid_size)
        Action.objects.create(
            room=room, player=me, action_type='sonar',
            target_row=origin_row, target_col=int(angle),
            result=result,
        )
    else:  # fire
        target_row = data.get('target_row')
        target_col = data.get('target_col')
        if not (0 <= target_row < room.grid_size and 0 <= target_col < room.grid_size):
            return JsonResponse({'error': 'Target out of bounds'}, status=400)
        result = _process_fire(target_row, target_col, enemy)
        Action.objects.create(
            room=room, player=me, action_type='fire',
            target_row=target_row, target_col=target_col,
            result=result,
        )

    # Check win condition
    if action_type == 'fire' and result.get('hit') and _check_win(enemy):
        room.status = 'finished'
        room.winner = me
        room.save()
        return JsonResponse({
            'result': result,
            'game_over': True,
            'winner': me.name,
        })

    # Switch turns
    room.current_turn = enemy
    room.save()

    return JsonResponse({
        'result': result,
        'game_over': False,
    })
