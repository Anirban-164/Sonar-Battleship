from django.contrib import admin
from game.models import Room, Player, Ship, Action


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('code', 'status', 'created_at')
    list_filter = ('status',)


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ('name', 'room', 'ships_placed', 'created_at')


@admin.register(Ship)
class ShipAdmin(admin.ModelAdmin):
    list_display = ('player', 'size', 'is_sunk')


@admin.register(Action)
class ActionAdmin(admin.ModelAdmin):
    list_display = ('action_type', 'player', 'target_row', 'target_col', 'created_at')
    list_filter = ('action_type',)
