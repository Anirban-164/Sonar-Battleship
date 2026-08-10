# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- **Initial Setup**: Established full project architecture for "Sonar Battleship", including Room, Player, Ship, Action models, polling logic, and basic game flow.
- **Angular Sonar System**: Replaced grid-coordinate cell-based sonar with a bearing-based angular system. Added an interactive SVG dial for players to select an angle (0° to 359°). The backend (`_angular_sonar`) now calculates the approximate distance to the nearest ship using a ±12° cone from the center of the enemy's grid.
- **Combined Grid Layout**: Introduced a wider, unified grid layout during the game phase. The left half displays the player's fleet and enemy attacks, while the right half displays the player's attacks on the enemy.
- **Ship-Cell-Based Sonar Origin**: Sonar now fires from a player-selected undamaged ship cell instead of the fixed grid center. In sonar mode, undamaged ship cells on the player's grid pulse with a cyan glow to indicate they are selectable. The player clicks a ship cell to set the sonar origin, then chooses a bearing angle and pings. Backend validates the origin cell belongs to the player and is undamaged. Sonar log and result displays now show the origin cell (e.g., "📡 B3 → 45° → ~2.5 cells").

### Fixed
- **Environment Migrations**: Fixed `DEFAULT_AUTO_FIELD` in `settings.py` to `BigAutoField` to resolve a `ValueError` during database migrations.
- **Database Sessions**: Resolved `ProgrammingError: relation "django_session" does not exist` by correctly re-running and verifying Django migrations (`python manage.py migrate`).
- **Imports**: Fixed and adjusted module imports across `game/admin.py`, `game/views.py`, and `game/urls.py` to ensure proper routing and model registration without errors.

### Changed
- **Game Views**: Refactored `api_action` in `game/views.py` to handle the new angle parameter for sonar actions while maintaining the cell target logic for fire actions.
- **UI & Styling**: Completely rewrote the game phase UI in `templates/game/room.html` and `static/game/style.css` to accommodate the unified grid layout and the new interactive sonar angle picker.
