"""
views.py — Django view functions (thin controllers).

Page views and API endpoints. All game logic is in game_logic.py,
all shared utilities are in helpers.py.
"""

import json
import random

from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.db import transaction

from game.models import Room, Player, Ship, Action
from game.helpers import (
    get_session_key,
    generate_room_code,
    get_player,
    get_enemy_player,
    get_player_position,
)
from game.game_logic import (
    SHIP_FLEET,
    validate_ship_placement,
    check_overlap,
    angular_sonar,
    dsp_sonar,
    process_fire,
    check_win,
)
from game.signal_engine import (
    generate_sonar_echo,
    generate_incoming_sonar_signals,
    generate_bomb_shockwave_signals,
    generate_idle_signals,
)
from game.signal_processor import process_signal


# ============================================================
# Page views
# ============================================================

def home(request):
    """Landing page — create or join a room."""
    get_session_key(request)  # ensure session exists
    return render(request, 'game/home.html')


def room(request, room_code):
    """Main game page for a specific room."""
    room_obj = get_object_or_404(Room, code=room_code.upper())
    session_key = get_session_key(request)
    player = get_player(room_obj, session_key)

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
# API views — Room management
# ============================================================

@csrf_exempt
@require_POST
def api_create_room(request):
    """Create a new room, add the creator as Player 1."""
    session_key = get_session_key(request)
    data = json.loads(request.body)
    player_name = data.get('name', 'Player 1')

    room = Room.objects.create(
        code=generate_room_code(),
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
    session_key = get_session_key(request)
    data = json.loads(request.body)
    room_code = data.get('code', '').upper().strip()
    player_name = data.get('name', 'Player 2')

    try:
        room = Room.objects.get(code=room_code)
    except Room.DoesNotExist:
        return JsonResponse({'error': 'Room not found'}, status=404)

    # Check if this session is already in the room
    existing = get_player(room, session_key)
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


# ============================================================
# API views — Game state polling
# ============================================================

@require_GET
def api_room_state(request, room_code):
    """
    Polled by the frontend every ~2-3 seconds.
    Returns the full game state visible to the requesting player.
    """
    room = get_object_or_404(Room, code=room_code.upper())
    session_key = get_session_key(request)
    me = get_player(room, session_key)

    if not me:
        return JsonResponse({'error': 'Not in this room'}, status=403)

    enemy = get_enemy_player(room, me)

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

    my_position = get_player_position(room, me)

    return JsonResponse({
        'status': room.status,
        'grid_size': room.grid_size,
        'current_turn': str(room.current_turn_id) if room.current_turn_id else None,
        'my_id': str(me.id),
        'is_my_turn': room.current_turn_id == me.id,
        'winner': str(room.winner_id) if room.winner_id else None,
        'my_position': my_position,
        'players': players_data,
        'my_ships': my_ships,
        'enemy_ships': enemy_ships,
        'my_actions': my_actions,
        'enemy_actions': enemy_actions,
        'ship_fleet': SHIP_FLEET,
    })


# ============================================================
# API views — Ship placement
# ============================================================

@csrf_exempt
@require_POST
def api_place_ships(request, room_code):
    """
    Player submits all their ship placements at once.
    Expects JSON: {"ships": [{"name": "Carrier", "cells": [[0,0],[0,1],...], "orientation": "H"}, ...]}
    """
    room = get_object_or_404(Room, code=room_code.upper())
    session_key = get_session_key(request)
    me = get_player(room, session_key)

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
        valid, error = validate_ship_placement(cells, size, room.grid_size)
        if not valid:
            # Rollback any created ships
            Ship.objects.filter(id__in=[s.id for s in created_ships]).delete()
            return JsonResponse({
                'error': f"Ship of size {size}: {error}"
            }, status=400)

        # Check overlap with already-placed ships in this submission
        if check_overlap(cells, all_cells):
            Ship.objects.filter(id__in=[s.id for s in created_ships]).delete()
            return JsonResponse({
                'error': f"Ship of size {size} overlaps with another ship"
            }, status=400)
        all_cells.extend(cells)

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
    enemy = get_enemy_player(room, me)
    if enemy and enemy.ships_placed:
        # Pick a random starting player
        first_player = random.choice([me, enemy])
        room.status = 'in_progress'
        room.current_turn = first_player
        room.save()

    return JsonResponse({'success': True})


# ============================================================
# API views — Turn actions (sonar / fire)
# ============================================================

@csrf_exempt
@require_POST
@transaction.atomic
def api_action(request, room_code):
    """
    Process a turn action.
    Sonar expects: {"action_type": "sonar", "angle": int}  (0-359 degrees)
    Fire expects:  {"action_type": "fire", "target_row": int, "target_col": int}
    """
    room = get_object_or_404(Room.objects.select_for_update(), code=room_code.upper())
    session_key = get_session_key(request)
    me = get_player(room, session_key)

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

    enemy = get_enemy_player(room, me)
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

        my_position = get_player_position(room, me)

        result = dsp_sonar(origin_row, origin_col, angle, enemy, me, room.grid_size, my_position)
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
        result = process_fire(target_row, target_col, enemy)
        Action.objects.create(
            room=room, player=me, action_type='fire',
            target_row=target_row, target_col=target_col,
            result=result,
        )

    # Check win condition
    if action_type == 'fire' and result.get('hit') and check_win(enemy):
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


# ============================================================
# API views — Signal data for oscilloscope display
# ============================================================

@require_GET
def api_signals(request, room_code):
    """
    Serves per-ship signal waveform data for the oscilloscope panel.
    Called by the frontend every poll cycle. Returns 600-sample arrays
    that get drawn as waveform traces on canvas elements.
    """
    room = get_object_or_404(Room, code=room_code.upper())
    session_key = get_session_key(request)
    me = get_player(room, session_key)

    if not me:
        return JsonResponse({'error': 'Not in this room'}, status=403)

    if room.status != 'in_progress':
        return JsonResponse({'signals': {}, 'event_type': 'idle'})

    enemy = get_enemy_player(room, me)
    my_position = get_player_position(room, me)

    # grab my ships as dicts for the signal engine
    my_ships = [{
        'size': s.size,
        'cells': s.cells,
        'hit_cells': s.hit_cells,
        'is_sunk': s.is_sunk,
    } for s in Ship.objects.filter(player=me)]

    if not my_ships:
        return JsonResponse({'signals': {}, 'event_type': 'idle'})

    # check if there's a new action we haven't rendered yet
    last_seen_id = request.GET.get('last_signal_action_id', '')
    latest_action = Action.objects.filter(room=room).order_by('-created_at').first()

    event_type = 'idle'
    signals = {}

    if latest_action and str(latest_action.id) != last_seen_id:
        if latest_action.player_id == me.id:
            # I fired sonar -> I hear my own echo
            if latest_action.action_type == 'sonar':
                event_type = 'sonar_echo'
                enemy_ships = []
                if enemy:
                    for s in Ship.objects.filter(player=enemy):
                        enemy_ships.append({
                            'cells': s.cells,
                            'hit_cells': s.hit_cells,
                            'is_sunk': s.is_sunk,
                        })
                # origin stored in result, angle stored in target_col
                origin_result = latest_action.result or {}
                origin = origin_result.get('origin', [latest_action.target_row, 0])
                angle = latest_action.target_col

                signals = generate_sonar_echo(
                    origin, angle,
                    my_ships, enemy_ships,
                    room.grid_size, my_position
                )
            else:
                # I fired a bomb — my ships hear the explosion's shockwave
                event_type = 'bomb_shockwave'
                signals = generate_bomb_shockwave_signals(
                    (latest_action.target_row, latest_action.target_col),
                    my_ships, room.grid_size, my_position
                )
        else:
            # enemy did something
            if latest_action.action_type == 'sonar':
                # enemy sonar ping passes near my ships
                event_type = 'incoming_sonar'
                origin_result = latest_action.result or {}
                enemy_origin = origin_result.get('origin', [0, 0])
                angle = latest_action.target_col

                signals = generate_incoming_sonar_signals(
                    enemy_origin, angle,
                    my_ships, room.grid_size, my_position
                )
            elif latest_action.action_type == 'fire':
                # enemy bomb -> shockwave
                event_type = 'bomb_shockwave'
                signals = generate_bomb_shockwave_signals(
                    (latest_action.target_row, latest_action.target_col),
                    my_ships, room.grid_size, my_position
                )
    else:
        # nothing new, just ocean noise
        signals = generate_idle_signals(len(my_ships))

    # run each ship's raw signal through the DSP pipeline
    processed_signals = {}
    for ship_idx, sig_data in signals.items():
        processed = process_signal(sig_data['signal'])
        processed_signals[ship_idx] = {
            'raw_signal': processed['raw_signal'],
            'noise_component': processed['noise_component'],
            'detected_signal': processed['detected_signal'],
            'detected': processed['detected'],
            'signal_type': processed['signal_type'],
            'confidence': processed['confidence'],
            'estimated_distance': processed['estimated_distance'],
            'peak_sample_index': processed['peak_sample_index'],
            'has_echo': processed['detected'],
        }

    return JsonResponse({
        'signals': processed_signals,
        'event_type': event_type,
        'action_id': str(latest_action.id) if latest_action else '',
    })
