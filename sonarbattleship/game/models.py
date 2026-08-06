import uuid
from django.db import models


class Room(models.Model):
    """A game room that two players join."""

    STATUS_CHOICES = [
        ('waiting', 'Waiting for Players'),
        ('placement', 'Ship Placement Phase'),
        ('in_progress', 'Game In Progress'),
        ('finished', 'Game Finished'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=6, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='waiting')
    grid_size = models.IntegerField(default=15)
    current_turn = models.ForeignKey(
        'Player', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='turn_room'
    )
    winner = models.ForeignKey(
        'Player', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='won_room'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'game_room'
        managed = False  # Schema managed via raw SQL on NeonDB

    def __str__(self):
        return f"Room {self.code} ({self.status})"


class Player(models.Model):
    """A player in a room, identified by Django session key."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='players')
    session_key = models.CharField(max_length=40)
    name = models.CharField(max_length=30, default='Player')
    ships_placed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'game_player'
        managed = False
        unique_together = [('room', 'session_key')]

    def __str__(self):
        return f"{self.name} in {self.room.code}"


class Ship(models.Model):
    """A ship belonging to a player. Spans multiple cells."""

    ORIENTATION_CHOICES = [('H', 'Horizontal'), ('V', 'Vertical')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='ships')
    size = models.IntegerField()
    cells = models.JSONField()         # [[row, col], [row, col], ...]
    orientation = models.CharField(max_length=1, choices=ORIENTATION_CHOICES, default='H')
    hit_cells = models.JSONField(default=list)  # [[row, col], ...] that have been hit
    is_sunk = models.BooleanField(default=False)

    class Meta:
        db_table = 'game_ship'
        managed = False

    def __str__(self):
        return f"({self.player.name})"


class Action(models.Model):
    """A turn action — either 'sonar' or 'fire'."""

    ACTION_CHOICES = [('sonar', 'Sonar'), ('fire', 'Fire')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='actions')
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='actions')
    action_type = models.CharField(max_length=5, choices=ACTION_CHOICES)
    target_row = models.IntegerField()
    target_col = models.IntegerField()
    result = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'game_action'
        managed = False
        ordering = ['created_at']

    def __str__(self):
        return f"{self.action_type} at ({self.target_row},{self.target_col}) by {self.player.name}"
