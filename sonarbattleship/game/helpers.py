"""
helpers.py — Shared utility functions for the game app.

Session management, player lookup, room code generation, and
player position resolution.
"""

import random
import string

from game.models import Room, Player


def get_session_key(request):
    """Ensure the request has a session and return its key."""
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def generate_room_code():
    """Generate a unique 6-character room code."""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not Room.objects.filter(code=code).exists():
            return code


def get_player(room, session_key):
    """Get the Player object for this session in this room, or None."""
    try:
        return Player.objects.get(room=room, session_key=session_key)
    except Player.DoesNotExist:
        return None


def get_enemy_player(room, current_player):
    """Get the other player in the room."""
    return Player.objects.filter(room=room).exclude(id=current_player.id).first()


def get_player_position(room, player):
    """
    Determine which side of the grid the player is on.
    First player (by created_at) = 'left', second = 'right'.
    """
    all_players = list(room.players.order_by('created_at'))
    if len(all_players) >= 2 and player.id == all_players[1].id:
        return 'right'
    return 'left'
