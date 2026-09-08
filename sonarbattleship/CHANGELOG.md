# Changelog

All notable changes to this project will be documented in this file.

## [0.5.2] — 2026-09-09

### Fixed
- **False Detection on Idle Signals**: Raised `DETECTION_THRESHOLD` from `0.08` to `0.30` in `signal_processor.py`. The old threshold was too low — pure ocean noise (AWGN with σ=0.15) routinely produced random matched-filter peaks above 0.08, causing the system to falsely report bomb or sonar detections when nothing had happened. The new threshold of 0.30 sits comfortably above the noise floor (~0.04 σ) while still catching real echoes (which peak at 0.4–0.9 after attenuation).
- **Filtered Signal & Noise Signal Looked Identical**: The `noise_component` output from `process_signal()` was previously set to `signal - filtered_signal` (the high-frequency residue removed by the bandpass filter). For broadband AWGN, this residue looks nearly identical to the raw signal, making the "Filtered Noise" and "Raw Signal" oscilloscope canvases indistinguishable. Now `noise_component` carries the **bandpass-filtered signal** instead, which is visually distinct — smoother, narrower band, lower amplitude.
- **Idle Oscilloscope Canvas Differentiation**: Updated the frontend idle animation so the "Filtered Signal" canvas uses IIR-smoothed low-amplitude noise (simulating bandpass filter output on AWGN) instead of raw Gaussian jitter, making it clearly distinct from the "Raw Signal" canvas at all times.

### Changed
- **Oscilloscope Layer Label**: Renamed the middle oscilloscope layer from "Filtered Noise" to "Filtered Signal" in `room.html` to accurately reflect that it now displays the bandpass-filtered waveform rather than the removed noise component.

## [0.5.1] — 2026-09-09


### Fixed
- **Oscilloscope 3×3 Grid Layout**: Fixed the signal processing panel so it correctly renders as a 3-column × 3-row grid (one column per ship, three signal layers per column). Previously the columns collapsed into 9 vertically stacked bars. Added `min-width: 0` and `overflow: hidden` to `.signal-ship-col` to prevent CSS grid blowout, and introduced a `ResizeObserver` to dynamically size each canvas to its container width instead of using a hardcoded 600px.
- **Pause-Rewind Scrubber**: The scrubber now performs a true time-domain rewind. Dragging the slider backward shows a partial waveform up to the scrub position (`signal.slice(0, sampleIdx + 1)`) on all three layers (raw, noise, detection), giving the visual effect of rewinding through the signal. Previously, the scrubber only drew a static yellow cursor line over the frozen full waveform, which was non-functional and confusing.
- **Idle Signal Differentiation**: The three oscilloscope layers now display visually distinct traces during idle (no-event) mode. Raw Signal shows full-amplitude ambient ocean noise (cyan), Filtered Noise shows low-amplitude residual jitter (gray, ×0.04 scale), and Detection Output shows a near-flat baseline (green, ×0.02 scale). Previously all three layers rendered identical noise at the same amplitude and color, making them indistinguishable.

### Changed
- **Sonar Controls Placement**: Moved the sonar angle picker, origin selector, fire hint, action result panel, and sonar readings log from the bottom panel (below the grid) into a sidebar that sits beside the combined grid. This eliminates the need to scroll up and down between the controls and the grid during gameplay. The layout uses a new `.game-main-area` flex container with a `.game-sidebar` (fixed 220–260px width) alongside the grid. On narrow screens (<900px), the sidebar stacks above the grid.

## [0.5.0] — 2026-09-01

### Added
- **Signal Engine Module**: Introduced `game/signal_engine.py` using NumPy to simulate acoustic waveforms. Models include Gaussian-windowed sine pulses (sonar pings), broadband shockwaves (bomb hits), Additive White Gaussian Noise (ocean ambient noise), and distance-based attenuation.
- **Oscilloscope UI**: Added a live signal oscilloscope panel to the game room. Each of the player's ships now has a dedicated hydrophone canvas trace with CRT-style scanline styling.
- **Signal API**: New endpoint `/api/signals/<room_code>/` serves 600-sample arrays (JSON) mapping to 3 seconds of acoustic data for the frontend to render.
- **Signal Playback Controls**: The oscilloscope automatically freezes when an event signal (echo, shockwave) is detected. Added a playback bar with Pause/Resume buttons, a scrubber slider, and a time readout, allowing players to visually analyze the waveform before returning to live ambient noise.
- **Fire Feedback**: When a player fires a bomb, they now receive a self-shockwave acoustic signal on their own oscilloscope, providing immediate acoustic feedback.
- **Signal Theory Documentation**: Added `Signal_Theory_Explained.tex` (LaTeX) providing a conceptual math and physics explanation of AWGN, Gaussian windows, attenuation, and time delays.

### Changed
- **Backend Modularization**: Refactored the monolithic 600-line `views.py` into a thin-controller architecture. Logic was extracted into `game/helpers.py` (session & player utilities) and `game/game_logic.py` (fleet validation, hit detection, sonar math).
- **Code Comments**: Humanized the docstrings inside `signal_engine.py` to replace dense academic formatting and Greek symbols with easy-to-read explanations.

## [0.4.0] — 2026-08-11

### Changed
- **Landing Page Redesign**: Completely replaced the old image-based landing page (`main_menu.png` overlay with invisible click zones) with the full "Visible" sonar-themed template design. The home page is now a standalone HTML page with its own design system instead of extending `base.html`.
- **New Design System**: Adopted the Visible template's premium dark sonar aesthetic with custom CSS variables for colors (`--green`, `--cyan`, `--bg-0` through `--bg-4`), typography (Rajdhani display font, Inter body font, JetBrains Mono monospace), and spacing.
- **Hero Section**: Added an animated hero with a rotating radar sweep, pulsing sonar ping rings, device mockups (tablet showing a radar scope with blips/reticle, phone showing signal processing waveforms), and three feature cards (Realistic Sonar, Sonar or Fire, Multi-cell Fleets).
- **Signal Chain Pipeline**: Added a "How a ping becomes a hit" section with six illustrated pipeline cards (Sonar Ping → Received Signal → Cross-Correlation → Matched Filter → Detection → Signal Strength), each with inline SVG art and animated elements.
- **Room Create/Join Modal**: Replaced the inline form-based room creation flow with a glassmorphic overlay modal. Clicking "Play Now" in the hero opens the modal with Create Room and Join Room panels side by side. Includes loading states on buttons, error toasts, backdrop click/Escape key dismissal, and auto-open when Django passes an error context.
- **Quote Section & Footer**: Added a styled quote strip and a minimal footer with the sonar brand mark and project attribution.

### Added
- `static/game/sonar-landing.css` — Full sonar theme stylesheet (CSS variables, header, hero, pipeline, footer, responsive breakpoints, scroll-reveal animations).
- `static/game/sonar-landing.js` — Page interaction script (mobile nav toggle, scroll-top button, sticky header shadow, IntersectionObserver scroll reveals).
- Bootstrap Icons loaded via CDN (`bootstrap-icons@1.11.3`) for UI icons throughout the landing page.
- Google Fonts loaded via CDN (Rajdhani, Inter, JetBrains Mono) for the new typography system.
- Scroll-to-top button with smooth scroll behavior.
- Responsive design with breakpoints at 1239px, 991px, 767px, and 480px.
- `prefers-reduced-motion` media query support to disable animations for accessibility.

### Removed
- Dependency on `main_menu.png` image for the landing page layout.
- Invisible percentage-based click zones for the "Play Now" button.
- Landing page's dependency on `base.html` template inheritance (now standalone).

---

## [Unreleased]

### Added
- **Initial Setup**: Established full project architecture for "Sonar Battleship", including Room, Player, Ship, Action models, polling logic, and basic game flow.
- **Angular Sonar System**: Replaced grid-coordinate cell-based sonar with a bearing-based angular system. Added an interactive SVG dial for players to select an angle (0° to 359°). The backend (`_angular_sonar`) now calculates the approximate distance to the nearest ship using a ±12° cone from the center of the enemy's grid.
- **Combined Grid Layout**: Introduced a wider, unified grid layout during the game phase. The left half displays the player's fleet and enemy attacks, while the right half displays the player's attacks on the enemy.
- **Ship-Cell-Based Sonar Origin**: Sonar now fires from a player-selected undamaged ship cell instead of the fixed grid center. In sonar mode, undamaged ship cells on the player's grid pulse with a cyan glow to indicate they are selectable. The player clicks a ship cell to set the sonar origin, then chooses a bearing angle and pings. Backend validates the origin cell belongs to the player and is undamaged. Sonar log and result displays now show the origin cell (e.g., "📡 B3 → 45° → ~2.5 cells").
- **Sonar Beam Visualization**: Added a live SVG overlay to the combined grid. When a sonar origin is selected and an angle is chosen, a beam cone (±12°) is drawn from the origin cell across the grid, updating in real-time as the angle is adjusted.
- **Explosion Animations**: Implemented a 6-frame explosion sprite animation that triggers immediately when firing. The animation is displayed instantly for the attacker to provide satisfying feedback, and the defending player sees the same explosion on their grid on the next polling cycle.
- **Landing Page**: Added a custom main menu image as a landing page before room creation. Users can click the "Play Now" button area (dynamically calculated via percentages) to enter the game setup.

### Changed
- **Static Facing Grid**: Transformed the game UI from a relative layout (player always on left) to a static, absolute spatial layout. Player 1 is always positioned on the left side of the grid, and Player 2 is always on the right side. Both players now see the exact same spatial arrangement, making the fleets "face each other" across the divider. Grid labels ("YOUR FLEET" / "ENEMY WATERS") update dynamically based on the player's position.

### Fixed
- **Environment Migrations**: Fixed `DEFAULT_AUTO_FIELD` in `settings.py` to `BigAutoField` to resolve a `ValueError` during database migrations.
- **Database Sessions**: Resolved `ProgrammingError: relation "django_session" does not exist` by correctly re-running and verifying Django migrations (`python manage.py migrate`).
- **Imports**: Fixed and adjusted module imports across `game/admin.py`, `game/views.py`, and `game/urls.py` to ensure proper routing and model registration without errors.

### Changed
- **Game Views**: Refactored `api_action` in `game/views.py` to handle the new angle parameter for sonar actions while maintaining the cell target logic for fire actions.
- **UI & Styling**: Completely rewrote the game phase UI in `templates/game/room.html` and `static/game/style.css` to accommodate the unified grid layout and the new interactive sonar angle picker.
- **Submarine Images**: Replaced plain colored grid cells with actual submarine sprites (`sub3.png`, `sub4.png`, `sub5.png` from `resources/images/`). Ships are rendered as absolutely-positioned images spanning the full length of the ship. Horizontal ships are flipped (since sprites face left), vertical ships are rotated 90°. The sprites are enhanced with high brightness and a cyan glow drop-shadow to stand out against the deep sea background.
- **Ocean Background**: Set `background.png` (deep ocean scene) as the full-page background with `background-attachment: fixed`. UI panels now use semi-transparent backgrounds with `backdrop-filter: blur()` for a glass-morphism effect.
- **Hit/Sunk Overlays**: Hit cells now display a red-tinted semi-transparent overlay with `backdrop-filter: blur(2px)` over the ship image. Sunk cells use a darker overlay with `grayscale(1)` and stronger blur, visually indicating destruction without removing the ship sprite.
