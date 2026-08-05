# Sonar Battleship — Step-by-Step Build Guide (v2)

A practical, week-by-week build order. Each week assumes ~5 hrs/person (~10 hrs/week combined). Steps within a week are ordered — do them in sequence, since later steps depend on earlier ones working.

---

## What changed since the first draft

After talking through the design in more depth, we made a few changes to the original plan:

- **Dropped ship movement.** It solves the "found once, dead forever" problem, but at a steep implementation cost (position history, collision detection, boundary checks) for very little DSP payoff. Not worth it on this timeline.
- **Split "ping" into two separate turn actions: Sonar and Fire.** In the original plan, a single ping both detected *and* damaged a ship. Now a player chooses one action per turn:
  - **Sonar** — pure reconnaissance. Costs a turn, does no damage, returns information.
  - **Fire** — pure attack. Costs a turn, does damage, but you're shooting blind unless your sonar reads told you something.
  This is closer to how real sonar works (it listens, it doesn't shoot), and it gives the DSP layer actual gameplay weight — every sonar read is a turn spent instead of firing.
- **Sonar returns distance, not coordinates.** Pinging a cell tells you *"something is approximately D cells away from here"* — a ring of possible positions, not a single cell. One reading narrows things down; two or more readings from different cells let you triangulate. This, plus multi-cell ships below, is our actual answer to "won't the enemy just keep hitting the same spot once they find it" — noise alone wasn't a strong enough defense against that.
- **Ships now span multiple cells (3–5), like classic Battleship.** Finding a ship's approximate location isn't the same as sinking it — you still need to figure out which cells it occupies and hit each one. This is the single biggest fix for the "found once = dead" problem.
- **Directional (bearing-based) sonar is now an explicit stretch goal**, not part of the core build. It's the most DSP-interesting version of the idea (player picks an angle instead of a cell, backend finds range along that bearing), but it needs a different UI (angle picker, bearing+range readout instead of grid click) and isn't worth the risk before the core loop is solid. Revisit it in Week 6 only if you're ahead of schedule.

Everything below reflects these decisions.

---

## Week 1 — Skeleton & Multiplayer Plumbing (no game logic yet)

**Goal:** two browsers/devices can join the "same game" and see shared state update.

1. `django-admin startproject sonarbattleship` + one app, e.g. `game`.
2. Design the DB models (this is the backbone — get it right early):
   - `Room` (code, created_at, status)
   - `Player` (room FK, session/device id, name, is_turn)
   - `Ship` (player FK, coordinates — a list of 3–5 adjacent cells, not a single point, size, hit_cells)
   - `Action` (room FK, player FK, action_type: `'sonar'` or `'fire'`, target_cell, timestamp, result — filled in later weeks). This replaces the old single `Ping` model, since a turn is now either a sonar read or a missile shot, never both.
3. Build a minimal "create room" → generates a short room code → "join room" (enter code) flow. No auth needed; just a session-based player identifier.
4. Build a bare page that polls the backend every ~2–3 seconds (`fetch` + `setInterval`) and displays raw JSON of room state. Ugly is fine — you're proving the sync works.
5. **Checkpoint:** open the app on two separate devices/browsers, join the same room code, and confirm both see the same `Player` list update within a few seconds. If this works, your entire multiplayer foundation is done — everything else builds on top of it.

---

## Week 2 — Real Game Loop (still no signal processing)

**Goal:** a fully playable, boring version of Battleship — including the sonar/fire split — proves the *game* works before you add DSP on top.

1. Ship placement UI: player places ships as **runs of 3–5 adjacent cells** (or auto-random-place for now, refine later). Reject overlapping or non-adjacent placements.
2. Turn logic: the active player picks one action — **Sonar** or **Fire** — then control passes to the other player. Only the active player can act.
3. Boring-mode Sonar: no DSP yet. Just compute straight-line (Euclidean) distance from the pinged cell to the *nearest* enemy ship cell, and return that number. This is already meaningfully different from a hit/miss lookup — the player gets a distance, not a location.
4. Boring-mode Fire: direct lookup — does the targeted cell exactly match an enemy ship cell? Hit / miss, and mark a ship "sunk" once all its cells are hit.
5. Win condition: all cells of all of a player's ships hit → game over screen.
6. Polish the grid UI slightly (still can be plain CSS, styling comes in Week 5).
7. **Checkpoint:** you and your teammate should be able to play a full game start-to-finish on two devices — choosing sonar vs. fire each turn, using sonar distance hints to narrow down where to fire, and sinking multi-cell ships. This is your fallback demo if later weeks run over — never skip this checkpoint.

---

## Week 3 — Signal Simulation Layer

**Goal:** replace the boring straight-line-distance Sonar action with a simulated sonar signal — but don't do detection yet, just generate and display it. (Fire stays a direct lookup; it doesn't need this layer.)

1. Define a **pulse shape** — e.g. a short Gaussian-windowed sine burst (`numpy`: `np.exp(-t**2/width) * np.sin(2*pi*f*t)`). This is your "ping."
2. When a player uses Sonar on a cell, simulate the round trip **from that cell**:
   - Compute the **true delay** based on the distance from the pinged cell to the nearest enemy ship cell (you decide the mapping — e.g. distance → time delay via an assumed "speed of sound"). The pinged cell is the reference point, not a fixed home base.
   - Build the **echo**: the same pulse shape, shifted by that delay, scaled down in amplitude (attenuation), only if a ship cell is within detection range — otherwise just noise.
3. Add **noise**: Gaussian random noise added to the whole received signal (`np.random.normal`). Make the noise level a parameter you can tune.
4. Return the raw noisy signal (as an array/JSON) from the backend to the frontend.
5. Plot it on the frontend (any simple line chart — Chart.js, or Canvas manually) so you can *see* a noisy waveform with a hidden echo bump in it.
6. **Checkpoint:** for a Sonar action near a ship, you should be able to squint at the plotted signal and roughly see the echo bump above the noise floor. Pinging empty water should look like pure noise. If you can't see any visual difference even before adding detection, your pulse amplitude/noise levels need tuning now — much easier to fix before Week 4 builds on top of it.

---

## Week 4 — Detection: The Actual DSP Core

**Goal:** replace "look at the plot yourself" with an algorithm that decides Sonar's output — an estimated distance and a confidence — from the noisy signal. Fire remains the simple direct lookup from Week 2; it doesn't touch this layer.

1. Implement **cross-correlation / matched filtering**: correlate the known pulse template against the received noisy signal (`np.correlate` or `scipy.signal.correlate`). This is the one non-negotiable core algorithm — get it right and everything downstream (distance estimate, detection confidence) follows from it.
2. Find the **peak** of the correlation output — its position corresponds to the estimated delay; its height corresponds to detection confidence.
3. Convert delay → **estimated distance** using the same mapping you used in Week 3 (inverse of the distance→delay function). This is the number the Sonar action returns to the player — a distance from the pinged cell, with error that grows as noise increases, not a coordinate.
4. Set a **detection threshold**: if peak height is above the threshold, report "contact, approximately D cells away." If below, report "no contact" — which can be a false negative if a ship was actually in range but the noise swamped the peak. Occasionally a noise spike above threshold with no ship nearby gives a false alarm — both effects are expected and are the point.
5. Wire this into the Week 2 Sonar action (replace the straight-line-distance placeholder with this DSP-based estimate). Fire logic is untouched.
6. **Checkpoint:** play a full game again, this time with noise fully driving Sonar's reliability. Try a couple of different noise levels and confirm detection quality (accuracy of the distance estimate, and how often you get contact/no-contact right) gets visibly worse as noise increases — that relationship *is* your project's core technical contribution, so it needs to be real and demonstrable, not just plausible-looking.

---

## Week 5 — Visual Polish & Difficulty

**Goal:** turn the working-but-plain prototype into something that looks and feels like a game.

1. Apply the visual direction from your earlier reference (dark navy/black background, glowing cyan/green sonar-screen palette).
2. Add the **ping ripple animation** on the grid for Sonar actions, and a distinct flash/impact animation for Fire.
3. Add a **distance-ring overlay**: after a Sonar read, draw a ring (or annulus, if you want to show the uncertainty band) around the pinged cell at the estimated distance. This is the visual payoff of "distance, not coordinates" — it should visibly make the player think in terms of narrowing down a region, not a single cell. Multiple sonar reads should let a careful player see where rings from different pings overlap.
4. Style the waveform/correlation plot like an oscilloscope trace (glowing line, dark background) instead of a default chart-library look.
5. Add a **noise-level slider or difficulty setting** players choose before starting (easy = low noise = tight rings, reliable contact; hard = high noise = wide rings, unreliable contact).
6. Small UX passes: turn indicator, action picker (Sonar vs. Fire), "waiting for opponent" state, sunk-ship feedback, game-over screen.
7. **Checkpoint:** show the app to someone outside your team (classmate, roommate) without explaining anything first — if they can figure out how to play (including the sonar/fire choice) within a minute, the UI is doing its job.

---

## Week 6 — Testing, Hardening, Demo Prep

**Goal:** make sure it survives being shown live, and package the explanation.

1. Cross-device testing: real two-device play (not just two browser tabs) — catch polling/timing bugs, mobile layout issues.
2. Edge cases: player disconnects mid-game, both players target the same cell, room codes colliding, refresh mid-game (does state reload correctly?), a Fire on a cell already confirmed sunk.
3. Bug-fix pass based on the above.
4. Write the short DSP write-up: what the matched filter is doing, and a couple of example plots showing detection accuracy at low vs. high noise (accuracy vs. noise level — a nice concrete result to show).
5. Prepare a **live demo script**: which room/game state you'll show, in what order — make sure it demonstrates the sonar/fire split and a multi-cell ship being narrowed down and sunk, not just a single lucky hit. Plan this so the demo doesn't depend on things going right on the first try live.
6. Optional, only if ahead of schedule: pick **one** stretch goal rather than several — better to ship one polished extra than three half-done ones. **Directional (bearing-based) sonar** is our recommended pick: the player selects a bearing instead of a cell, the backend finds the nearest ship along that direction, and the result is reported as "bearing + estimated range" instead of a grid cell. The DSP is identical (same cross-correlation), so it's mostly a UI addition (angle picker, bearing/range readout) — but it's the most educationally interesting extension if time allows.

---

## A few build-order principles worth keeping in mind

- **Game loop before signal processing, always.** Week 2's checkpoint (plain, boring, fully working Battleship with the sonar/fire split already in place) is your safety net — if Weeks 3–4 run into trouble, you still have a demoable project.
- **Signal simulation before detection.** You can't tune a detector against a signal you haven't looked at yet — Week 3's "just plot it and eyeball it" step is not a waste of time, it's what makes Week 4 debuggable instead of guesswork.
- **Structural game design carries some of the weight DSP alone can't.** Noise makes detection unreliable, but on its own it isn't enough to stop "find once, keep firing." Multi-cell ships, distance-not-coordinates sonar readings, and the action economy of splitting sonar from fire all combine to make the game genuinely strategic — don't rely on noise level to do that job by itself.
- **Visual polish last, on purpose.** It's tempting to make it look nice early since that's the fun part, but a beautiful UI wrapped around broken detection logic is a worse demo than a plain UI with correct detection. Week 5 exists specifically so polish doesn't eat into DSP time.
