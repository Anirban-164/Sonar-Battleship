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
    counter_detect,
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
# Visibility helpers
# ============================================================

# Fields of an Action.result that belong to the OPPONENT of the player
# who took the action, and must never be served back to the actor.
#
# 'counter_detection' is the opponent's passive-sonar report: how well
# their hydrophones heard this ping and where they think it came from.
# Handing that to the player who pinged would tell them how far away the
# enemy fleet is — the exact information they just paid a turn trying to
# get, for free, and from the wrong side of the board.
PRIVATE_RESULT_FIELDS = ('counter_detection',)


def strip_private_action_fields(result):
    """Return a copy of an action result safe to show to its own author."""
    if not isinstance(result, dict):
        return result
    if not any(k in result for k in PRIVATE_RESULT_FIELDS):
        return result
    return {k: v for k, v in result.items() if k not in PRIVATE_RESULT_FIELDS}


def redact_enemy_action_result(action_type, result):
    """
    Cut an opponent's action down to what we are entitled to know.

    A sonar action's stored result is mostly the *attacker's* private
    business: which of their own cells they transmitted from, what their
    detector made of the return, how confident it was. Handing all of
    that to the player being pinged would give away the attacker's exact
    position for free — which is both wrong and would make passive
    counter-detection pointless, since the answer it works so hard to
    estimate would already be sitting in the same payload.

    So for a sonar action we keep exactly one thing: the counter-detection
    report, which is what OUR hydrophones heard and is ours by right.

    Fire actions are different — the bomb landed on our grid, we can see
    the splash, and hit/sunk is information we already have.
    """
    if not isinstance(result, dict):
        return result
    if action_type != 'sonar':
        return result
    return {'counter_detection': result.get('counter_detection')}


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
            # My own sonar: I never learn whether the enemy heard me.
            'result': strip_private_action_fields(a.result),
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
                'result': redact_enemy_action_result(a.action_type, a.result),
            }
            if a.action_type != 'sonar':
                action_data['target'] = [a.target_row, a.target_col]
            # Deliberately no 'origin' and no 'bearing' for enemy sonar:
            # where they transmitted from, and along which bearing, is
            # exactly what our hydrophones are supposed to have to work
            # out for themselves.
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

        # Active sonar gives away the boat that used it. Work out what the
        # opponent's hydrophones make of the transmission and file it with
        # the action — strip_private_action_fields() below keeps it out of
        # the pinging player's own view, because a real submarine has no
        # way of knowing whether anyone was listening.
        enemy_position = get_player_position(room, enemy)
        result['counter_detection'] = counter_detect(
            [origin_row, origin_col], angle, enemy,
            room.grid_size, enemy_position,
        )

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

    # The immediate response goes to the player who just acted, so the
    # opponent's passive-sonar report is stripped here too.
    public_result = strip_private_action_fields(result)

    # Check win condition
    if action_type == 'fire' and result.get('hit') and check_win(enemy):
        room.status = 'finished'
        room.winner = me
        room.save()
        return JsonResponse({
            'result': public_result,
            'game_over': True,
            'winner': me.name,
        })

    # Switch turns
    room.current_turn = enemy
    room.save()

    return JsonResponse({
        'result': public_result,
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
    _origin_ship_idx = None

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

                # figure out which ship index fired the sonar
                import math as _math
                _origin_ship_idx = 0
                _best_d = float('inf')
                for _i, _s in enumerate(my_ships):
                    for _c in (_s.get('cells') or []):
                        _d = _math.sqrt((_c[0] - origin[0])**2 + (_c[1] - origin[1])**2)
                        if _d < _best_d:
                            _best_d = _d
                            _origin_ship_idx = _i
            else:
                # I fired a bomb — my ships hear the explosion, and if it
                # struck a hull they hear that break up too. The two are
                # deliberately different waveforms so the detector can
                # tell a hit from a miss without being told.
                fire_result = latest_action.result or {}
                was_hit = bool(fire_result.get('hit'))
                event_type = 'bomb_hit' if was_hit else 'bomb_miss'
                signals = generate_bomb_shockwave_signals(
                    (latest_action.target_row, latest_action.target_col),
                    my_ships, room.grid_size, my_position,
                    target_side='enemy',          # I aimed at their grid
                    hit=was_hit,
                    hit_ship_size=fire_result.get('ship_size'),
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
                # Enemy bomb — it landed on MY grid, so the blast is in my
                # own coordinate frame. Passing target_side='mine' is what
                # stops the defender's hydrophones computing the range as
                # if the explosion were a whole grid away.
                fire_result = latest_action.result or {}
                was_hit = bool(fire_result.get('hit'))
                event_type = 'bomb_hit' if was_hit else 'bomb_miss'
                signals = generate_bomb_shockwave_signals(
                    (latest_action.target_row, latest_action.target_col),
                    my_ships, room.grid_size, my_position,
                    target_side='mine',
                    hit=was_hit,
                    hit_ship_size=fire_result.get('ship_size'),
                )
    else:
        # nothing new, just ocean noise
        signals = generate_idle_signals(len(my_ships))

    # For bomb events, identify which ship was closest to the blast
    # (i.e. the one actually hit) so the frontend highlights the right column.
    _hit_ship_idx = None
    if event_type in ('bomb_hit', 'bomb_miss') and latest_action:
        import math as _math
        blast_r, blast_c = latest_action.target_row, latest_action.target_col
        _best_blast_d = float('inf')
        for _i, _s in enumerate(my_ships):
            if _s.get('is_sunk', False):
                continue
            for _c in (_s.get('cells') or []):
                _d = _math.sqrt((_c[0] - blast_r)**2 + (_c[1] - blast_c)**2)
                if _d < _best_blast_d:
                    _best_blast_d = _d
                    _hit_ship_idx = _i

    # run each ship's raw signal through the DSP pipeline
    # skip sunk ships entirely — a wreck can't listen
    processed_signals = {}
    best_peak_idx = None
    best_peak_conf = -1

    for ship_idx, sig_data in signals.items():
        idx_int = int(ship_idx)
        # skip sunk ships
        if idx_int < len(my_ships) and my_ships[idx_int].get('is_sunk', False):
            continue

        processed = process_signal(sig_data['signal'])

        # An enemy ping sweeping past us is a DIRECT arrival, not an echo
        # off something — so the one-way reading is the correct one. The
        # detector hands back both hypotheses precisely so the caller,
        # which knows what kind of event this was, can choose.
        distance = processed['estimated_distance']
        if event_type == 'incoming_sonar':
            distance = processed['estimated_distance_direct']

        conf = processed['confidence']
        if conf > best_peak_conf:
            best_peak_conf = conf
            best_peak_idx = idx_int

        processed_signals[ship_idx] = {
            'raw_signal': processed['raw_signal'],
            'noise_component': processed['noise_component'],
            'detected_signal': processed['detected_signal'],
            'detected': processed['detected'],
            'signal_type': processed['signal_type'],
            'signal_class': processed['signal_class'],
            'confidence': processed['confidence'],
            'snr': processed['snr'],
            'estimated_distance': distance,
            'estimated_size': processed['estimated_size'],
            'hull_ring': processed['hull_ring'],
            'peak_sample_index': processed['peak_sample_index'],
            'has_echo': processed['detected'],
            # what the physics engine actually did, so the sonar ping
            # that bounced off our own hull can be labelled as such
            'blocked': bool(sig_data.get('blocked')),
            'blocked_by_size': sig_data.get('blocked_by_size'),
        }

    # origin_ship_idx: which of my ships fired the sonar (for sonar_echo only)
    origin_idx = _origin_ship_idx if event_type == 'sonar_echo' else None

    # For bomb events, override best_ship_idx with the ship that was
    # actually closest to the blast (the one that should show the signal).
    effective_best = _hit_ship_idx if _hit_ship_idx is not None else best_peak_idx

    return JsonResponse({
        'signals': processed_signals,
        'event_type': event_type,
        'action_id': str(latest_action.id) if latest_action else '',
        'origin_ship_idx': origin_idx,
        'best_ship_idx': effective_best,
        'hit_ship_idx': _hit_ship_idx,
    })
