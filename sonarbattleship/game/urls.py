from django.urls import path
from game import views

app_name = 'game'

urlpatterns = [
    # --- Page routes ---
    path('', views.home, name='home'),
    path('room/<str:room_code>/', views.room, name='room'),

    # --- API routes (called by JS via fetch) ---
    path('api/create-room/', views.api_create_room, name='api_create_room'),
    path('api/join-room/', views.api_join_room, name='api_join_room'),
    path('api/room-state/<str:room_code>/', views.api_room_state, name='api_room_state'),
    path('api/place-ships/<str:room_code>/', views.api_place_ships, name='api_place_ships'),

    # --- Week 2 API routes ---
    path('api/action/<str:room_code>/', views.api_action, name='api_action'),

    # --- Week 3 API routes ---
    path('api/signals/<str:room_code>/', views.api_signals, name='api_signals'),
]
