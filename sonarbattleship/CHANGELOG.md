# Changelog

All notable changes to this project will be documented in this file.

## [0.7.2] — 2026-09-12

### Changed
- **Type Scale Raised**: everything in the console was set too small to read at a glance. Bumped roughly one step across the board — contact tables 0.63 → 0.76rem, panel titles 0.66 → 0.8rem, status chips 0.56 → 0.66rem, the bearing and origin readouts to 1.15rem, the passive-intercept summary to 0.88rem, and the oscilloscope's labels and detection readouts to match. Grid coordinate headers, fleet labels and the status badge went up too. Cell padding grew with the text so the tables keep their spacing.
- **Sidebar Widened To Match**: 292 → 336px, so the larger text still fits its columns instead of clipping the RESULT column again.
- **Bearing Dial Enlarged**: the ring is now 208px and its `viewBox` padded to `-122 -122 244 244`. At 13px the three-digit degree labels overran the old bounds and were sliced — the same clipping as before, reintroduced by the bigger type. The viewBox has to stay square and centred on (0,0), because the click handler maps the element's centre to bearing 000.
- Stylesheet cache buster bumped to `?v=0.7.2`.

## [0.7.1] — 2026-09-12

### Fixed
- **Stylesheet Was Being Served From Browser Cache**: the 0.7.0 styles were on disk but not reaching the page, which looked like four separate bugs and was one. Without them: the military fonts were declared but never applied, the contact tables rendered as bare HTML tables with columns running together, the sonar log kept its old `max-height` and grew a second scrollbar, and — the loudest symptom — `#passive-contact-overlay` never got `position: absolute`, so the contact SVG fell into normal document flow and drew *below* the grid instead of on it. Django's dev server sends a `Last-Modified` header that browsers hold on to, so an edited `style.css` keeps serving stale bytes until a hard refresh. `base.html` now loads it as `style.css?v=0.7.1`; bump that string whenever the stylesheet changes.
- **Bearing Dial Labels Clipped**: the dial's `viewBox` was `-100 -100 200 200` but the 90° and 270° labels were drawn at x = ±96 with `text-anchor` pointing outward, so they ran past the edge and were sliced in half. Padded to `-112 -112 224 224`.

### Changed
- **Sidebar Rebuilt As One Console**: it was a stack of differently-shaped boxes at different widths. The bearing selector is now a panel like the two logs, all three at one width with a single gutter. The dial gained a proper tick ring (every 15°, longer at 45°, longest on the cardinals) and lost its N/E/S/W letters, which collided with the degree labels at this size — the numbers are what the player types anyway. Bearing and origin are now compact key/value rows, and the chosen bearing is echoed in the panel header.
- **EMCON Warning Cut Down**: five lines of shouting capitals that pushed the contact log off the bottom of the panel, now a single quiet line on an amber rule.
- **Contact Tables Made Readable**: this was the "hard to classify" part. Column headers are words rather than initials (FROM / BRG / RANGE / HULL / CONF / RESULT, and HEARD BY / BRG / RANGE / HULLS / CONF), each with a tooltip saying what it means and what unit it is in. Cells have real padding so figures stop running together — `045°2.8` now reads as two columns. Status chips are short (`CONTACT`, `EMPTY`, `BLOCKED`) with the detail in the tooltip, which stops the RESULT column being clipped off the panel edge.
- **Passive Intercept Summary**: a row of numbers still needed trigonometry to act on, so the newest intercept is now also spelled out in plain language above the table — who heard it, the bearing and range, and the **estimated position as a cell with a ± search radius** derived from the multilateration residual. `counter_detect()` returns `fix_cell` and `fix_radius` for this.
- **Contact Overlay Reads As A Search Area**: the fix is drawn as a dashed box over the enemy grid covering `fix_cell ± fix_radius`, rather than a crosshair on a single cell — multilateration on noisy arrival times does not support that much precision. The full range circle is now drawn only when range is all we have; once a bearing is fixed, a circle sweeping the whole board buried the search area under it.

## [0.7.0] — 2026-09-12

### Added
- **Passive Counter-Detection — Active Sonar Discloses Your Position**: Pinging now gives you away, the way it does on a real submarine. The opponent's hydrophones already received the outgoing pulse (`generate_incoming_sonar_signals`); that signal was only ever drawn as a waveform and thrown away. It now runs through the full DSP chain on the listener's side and becomes a contact report: estimated **range** to the transmitting boat, and a **bearing** when the listening fleet can manage one.
  - **Multilateration.** One hydrophone measures how far away a transmitter is (from arrival delay) but carries no direction information, so a fleet down to its last boat gets a range circle only. Two or more boats, each with its own measured range, pin the source down by least squares over the 100 candidate cells — a search rather than an algebraic solve, so it cannot diverge on noisy ranges and can only return a cell that exists. Median bearing error ≈ 7°, median range error ≈ 1.0 cell.
  - **It is not a dice roll.** You are counter-detected if and only if the listener's matched filter clears its threshold, so it degrades with range, off-axis angle and noise exactly like every other detection in the game. At the default noise level a ping aimed at the enemy fleet is heard ~96% of the time and yields a full bearing fix ~47% of the time; at σ = 0.30 it is heard 9% of the time.
- **Transducer Radiation Pattern**: a transmitting sonar is not a laser. `transducer_gain()` gives full amplitude inside the main lobe, then an exponential falloff with off-axis angle (`SIDE_LOBE_LEVEL`, `SIDE_LOBE_FALLOFF_DEG`). A ping 30° off the enemy's bearing is still heard 92% of the time; 60° off, 7%; aimed away, 0%. This is what gives active sonar its cost — the beam has to point at the enemy fleet to find anything, and that is precisely the bearing on which they hear you best.
- **Contact Log Rebuilt As Military Tables**: the sonar readings list is now an **ACTIVE SONAR — CONTACT LOG** table (ORG / BRG / RNG / SZ / CNF / STATUS) with zero-padded bearings, tabular figures, status chips (CONTACT / NO CONTACT / BLOCKED) and an inline confidence bar. Beneath it, a new **PASSIVE — COUNTER-DETECTION** board (HYD / BRG / RNG / HP / CNF / FIX) lists hostile transmissions your hydrophones picked up, and flashes when a new one arrives.
- **Passive Contact Overlay**: the last hostile transmission is drawn on the grid — a dashed range arc centred on the hydrophone that heard it, plus a bearing ray and crosshair when the fleet achieved a fix. Its own SVG layer, so it survives the aiming beam being cleared.
- **EMCON Warning**: a permanent caution under the ping button. It has to be permanent — the transmitting player is never told whether they were actually heard, which is the point.

### Changed
- **Military Typography**: headings and hull markings in a stencil face (Black Ops One, falling back to Stardos Stencil), every instrument readout — bearings, ranges, confidence, both contact tables, grid headers, oscilloscope labels — in Share Tech Mono so digits line up in columns, and Saira Condensed for the UI text in between. Loaded in `base.html`, which also gains a `{% block head %}`. Status badges lost their rounded-pill shape in favour of squared placards.

### Fixed
- **Enemy Sonar Leaked The Attacker's Exact Position**: `api_room_state` served the opponent the full stored result of every enemy sonar action — including `origin`, the precise cell they transmitted from, plus their range, contact flag, estimated target size and confidence. The defender was simply handed the attacker's submarine location, which is both wrong on its own and would have made passive counter-detection pointless, since the answer it works to estimate was already in the same payload. An enemy sonar action is now redacted to the counter-detection report alone, with no `origin` and no `bearing`. Fire actions are unchanged — the bomb landed on your grid, you can see the splash.
- **Counter-Detection Never Reaches The Pinger**: the report is stored on the attacker's own action row, so it is stripped from that player's view in both `api_room_state` (`my_actions`) and the immediate `api_action` response. A real submarine has no way of knowing whether anyone was listening.
- **Passive Beam Width**: incoming enemy pings were tested against double the beam half-width used everywhere else, so defenders heard transmissions aimed nowhere near them at full strength. All beam tests now share `BEAM_HALF_WIDTH`, with off-axis energy handled by the radiation pattern instead.

## [0.6.0] — 2026-09-12

### Fixed
- **Sonar Is Now Blocked By Allied Ships**: A ping fired along a bearing that passes through one of your own submarines no longer reaches the enemy. `signal_engine.find_beam_blocker()` walks the player's own fleet, and if a friendly hull sits inside the beam closer than the nearest enemy cell, the pulse reflects off it — the result is flagged `blocked`, no enemy distance is returned, and the turn is spent. The boat the ping is fired *from* never blocks itself, and sunk wrecks don't block. `angular_sonar()` applies the same rule.
- **Confidence Meter**: `confidence` was the raw matched-filter peak amplitude — an unbounded number that the UI multiplied by 100, so readouts above 100% were routine, and the value meant nothing comparable between a nearby blast and a distant echo. Confidence is now derived from the peak's signal-to-noise ratio against a noise floor measured from the correlation trace itself (median of the envelope away from the peak), mapped through a logistic to a strict 0–1. It reads 50% exactly at the detection threshold, is reported even when nothing is detected, and falls monotonically as noise rises (0.92 → 0.23 across σ = 0.05 → 0.70).
- **Bomb Hit and Miss Detected Separately**: A bomb produced one generic shockwave whether or not it struck anything. A hit now also emits a **hull rupture ring** — a short, high-frequency burst (12 Hz) 0.12 s after the blast front, in its own frequency band. A third matched-filter channel looks for it, so the detector reports `bomb_hit` or `bomb_miss` from the acoustics alone. Over 480 trials at full board range: hits classified correctly 100% of the time, misses never reported as hits.
- **Submarine Size Drives Detection**: Echo amplitude now scales as `sqrt(size / 3)` and echo width with hull length, and only the portion of a ship actually inside the beam contributes. The detector runs a **template bank** (one pulse shape per plausible submarine size) and inverts the attenuation model to recover the target's size from the echo — accurate to within ±1 cell on every trial, and to the exact size from a hull ring. Sonar and bomb readouts now say *what* was found, not just that something was.
- **Matched Filter Rewritten**: The correlator used a full-length template whose 'same'-mode output tapered to near-zero at both ends; any robust noise estimate over that trace was dominated by the dead edges, so **pure ocean noise was reported as a detection 82% of the time**. It is now a compact quadrature (sine/cosine) template pair with envelope detection — phase-independent, uniform across the trace, zero-padded so close-range events aren't clipped out of the search window, and restricted to physically possible (non-negative) delays. Idle false alarms: 0.2%.
- **Delay ↔ Distance Consistency**: Every generator placed its pulse at a different time origin (0.5 s for echoes, 0.3 s for incoming sonar, 0.4 s for shockwaves) while all templates assumed 0.5 s, biasing every range estimate. All pulses and templates now share `PULSE_ORIGIN_OFFSET`. Separately, echoes are round-trip and direct arrivals are one-way, but both were inverted with the same formula — `distance_to_delay` / `delay_to_distance` now take a `round_trip` flag and the detector returns both hypotheses so the caller picks. Range error on a detected contact is now ~0.1 cells.
- **Defender's Bomb Coordinates**: When the enemy bombed *your* grid, the shockwave range was computed as if the blast were on the opposite grid — a direct hit on your own hull registered as an event 9 cells away. `generate_bomb_shockwave_signals()` now takes `target_side` ('mine' / 'enemy').
- **Attenuation Rebalanced**: `ATTENUATION_ALPHA` was 0.3, tuned for a single 10-wide grid. With both fleets side by side every real sight line is 10–21 cells, so echoes arrived at about a fifth of source amplitude and were essentially undetectable — most "contacts" players saw were the detector misreading noise. At 0.12 a 5-cell boat is found consistently, a 3-cell boat at long range is roughly a coin flip, and noise level still drives the difference.
- **Overlapping Classifier Bands**: sonar (3–8 Hz) and bomb (0.5–4 Hz) overlapped, so one event appeared in both and the classifier was comparing two views of the same energy. Bands are now contiguous and disjoint: bomb 0.5–3, sonar 3–8, hull 8–17 Hz.
- **Sonar Origin Picked the Wrong Hydrophone**: `dsp_sonar()` chose which ship's recording to analyse by comparing only each ship's *first* cell to the origin, so firing from the tail of a long submarine could read a different, weaker boat's trace. It now matches the ship that actually contains the origin cell.
- **Beam Width Inconsistency**: three different half-widths were in use (10°, 12°, and 20° for incoming sonar). All beam tests now share `BEAM_HALF_WIDTH = 12°`; defenders no longer hear pings that never came near them.
- **Zero-Value Falsiness Bugs**: an `estimated_distance` of exactly 0 became `None`, and a peak marker at sample index 0 was never drawn. Both now test against `None` / `null`.
- **Already-Hit Cells**: firing into an existing hole returns `already_hit` and produces a miss shockwave with no hull ring — no second rupture from a hole that is already there.

### Added
- **Hull Ring Signature**: `HULL_FREQ`, `HULL_SIGMA`, `HULL_AMPLITUDE`, `HULL_RING_LAG` in `signal_engine.py`, plus a dedicated hull detection channel in `signal_processor.py`.
- **Target Size Estimation**: `signal_engine.target_strength()` / `size_pulse_width()` and their inverse `signal_processor.estimate_target_size()`, calibrated by measurement rather than algebra so the bandpass filter's own loss is accounted for.
- **Per-Channel Diagnostics**: `process_signal()` returns a `channels` block (SNR and peak for the sonar, bomb and hull channels, plus the winning size hypothesis) — useful for the DSP write-up and for tuning.
- **Richer Readouts**: the oscilloscope readout and the sonar log now show hit/miss, blocked-by-friendly-hull, estimated target size, and a sane confidence percentage. `process_fire()` returns `ship_size` so the signal engine can render the right hit signature.

### Changed
- **Oscilloscope Detection Trace**: the third canvas now shows the matched-filter *envelope* rather than the raw signed correlation — a single clean peak instead of an oscillating burst.
- **Timing Constants**: `PULSE_ORIGIN_OFFSET` 0.5 → 0.30 s, and `DELAY_PER_CELL` redefined as round-trip delay per cell at 0.12 s, so the longest sight line on the board (~21 cells) still lands its echo inside the 3-second recording window.

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
