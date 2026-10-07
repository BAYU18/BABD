# 2D Car Game — Design Spec

> **Single-file endless lane-dodger.** One `index.html`, HTML5 Canvas + vanilla JS,
> keyboard arrow controls, served from `192.168.0.222`. No external JS/CSS/images.
> This is a **bounded** build (one self-contained file, well-scoped by the Team Lead
> plan); the Team Lead owns the implementation plan/handoff, so this document is the
> design artifact the Developer builds from and QA tests against.

**File:** `/home/serverbot/aidev/index.html` (overwrite the existing hello-world file).
**Server:** static file server on `192.168.0.222`, recommended port **8080** (CEO to confirm).

---

## 1. HTML Structure

A single self-contained HTML5 document. No external resources of any kind.

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>2D Car Game</title>
  <style> /* all CSS inline here — see §6 */ </style>
</head>
<body>
  <canvas id="game" width="400" height="600"></canvas>
  <script> /* all JS inline here — see §2–§5 */ </script>
</body>
</html>
```

- Exactly one `<canvas id="game">`. Fixed logical viewport **400×600** (portrait, suits a
  vertical dodger). The canvas element keeps `width="400" height="600"` as its drawing
  buffer; CSS scales it responsively (see §6) while the game logic always works in the
  400×600 coordinate space.
- All CSS in one `<style>` block; all JS in one `<script>` block. **Zero** `<link>`,
  `<img>`, external `<script src>`, or fetch/XHR. The file must load and run fully offline
  from `file://` with no network.
- `<canvas>` is centered on the page; page background is a dark color so the canvas is
  visible against it.

### Why one canvas (not DOM elements)
The whole game (road, car, obstacles, score, overlays) is drawn into the canvas. This
keeps the public seam — the thing QA tests and the Developer implements — to **one file
with one element and one script**. No DOM game objects to keep in sync, no layout
thrash. The "module" is the file; its interface is the rendered, playable game.

---

## 2. Game Model

### Coordinate space
All game logic uses the canvas's 400×600 logical pixels. `x` grows rightward from the
left edge (0) to the right edge (400); `y` grows downward from the top (0) to the
bottom (600). The car drives "up" the screen conceptually, so obstacles and the road
scroll **downward** (increasing `y`).

### Lanes
The road is divided into **4 lanes** of equal width. Lane width = 400 / 4 = **100 px**.
Lane `i` (0-indexed) occupies x ∈ [i*100, (i+1)*100); its center x = `i*100 + 50`.

### The player car
- A colored rectangle: **width 40, height 70** (px). Color: a distinct solid fill
  (e.g. `#ffd93d` yellow) with a darker outline so it reads against the road.
- Fixed y near the bottom: `carY = 600 - 90 = 510` (top of the rect; bottom at 580,
  leaving a 20px margin from the canvas bottom).
- Lateral position is **lane-snapped**: the car occupies exactly one lane at a time.
  `carLane` is an integer in `[0, 3]`; the car's left edge x =
  `carLane*100 + (100-40)/2 = carLane*100 + 30`.
- **No continuous x movement**: Left/Right moves the car one whole lane (see §3).
  This makes bounds trivially correct (clamp `carLane` to `[0,3]`) and matches the
  CEO's "kontrol keyboard panah" intent simply and robustly.

### Obstacles
- Same dimensions as the car (40×70) for fair, readable collisions, drawn in a
  contrasting color (e.g. `#ff5c5c` red).
- Each obstacle has: `lane` (0–3), `y` (its top edge, starts at `-70` i.e. just off the
  top), and is drawn centered in its lane (same x formula as the car).
- Spawn rule: a new obstacle is created when `timeSinceLastSpawn >= spawnInterval`.
  Initial `spawnInterval = 1.1` seconds; it **decreases** as the score rises to ramp
  difficulty (see §4), floored at `0.45s` so it never becomes impossible.
- **No two obstacles in the same lane simultaneously** while one is still on screen in
  that lane — when spawning, pick a lane uniformly at random from lanes that are
  currently free (no active obstacle with that lane). If all lanes are occupied (rare),
  skip spawning this cycle. This guarantees the player always has an escape lane.
- Movement: every obstacle's `y += obstacleSpeed * dt`. Initial
  `obstacleSpeed = 140` px/s; it **increases** gradually with score (see §4), capped at
  `360` px/s.
- An obstacle is removed when `y > 600` (fully off the bottom). Passing an obstacle does
  not itself add score (score is time-based — §4) but survival is the point.

### Road / lanes rendering
- Road background: dark asphalt fill (e.g. `#1b2a1f` or `#222`) covering the full canvas.
- Lane dividers: dashed white lines between lanes (3 dividers, at x = 100, 200, 300),
  drawn as moving dashes to convey speed (dashes scroll downward with the obstacles at
  the same `obstacleSpeed`, wrapping when they pass the bottom).
- Optional road edge lines at x=0 and x=400 (solid white).
- The moving dashes are **purely visual** — they do not affect collision or scoring.

### Collision
- Collision = axis-aligned rectangle overlap between the player car rect and any
  obstacle rect. Because both are lane-aligned and same size, this is a simple AABB
  overlap test: `car.x < obs.x+40 && car.x+40 > obs.x && carY < obs.y+70 &&
  carY+70 > obs.y`.
- On collision: game enters the **GAME OVER** state (see §3), the loop stops updating
  obstacles/car, and the Game Over overlay is drawn.

---

## 3. Game Loop, States, and Controls

### States
The game has a small state machine:

| State | `state` value | What happens |
|---|---|---|
| Start screen | `"start"` | Overlay: title + "Press Space / ←→ to start". No movement. |
| Playing | `"playing"` | Loop updates car/obstacles/score; renders road, car, obstacles, score. |
| Game Over | `"over"` | Overlay: "Game Over", final score, high score, "Press Space / ←→ to restart". |

### Game loop
- `requestAnimationFrame` driven. Each frame computes `dt` (delta time in seconds)
  from the rAF timestamp: `dt = (now - last) / 1000`, clamped to a max of `0.05`
  (50 ms) to avoid huge jumps after tab-switches. If `dt <= 0`, skip.
- Update phase (only when `state === "playing"`): advance spawn timer, spawn if due,
  move obstacles, remove off-screen ones, check collisions, increment score, update
  difficulty (speed/spawnInterval) from score.
- Render phase (every frame): clear, draw road + dividers, draw obstacles, draw car,
  draw HUD (score, high score), draw overlay if `start` or `over`.

### Controls (keyboard)
- Listener on `document` (so focus is implicit — no need to click the canvas).
- `keydown`:
  - `ArrowLeft` / `ArrowRight`: in `"playing"`, move the car one lane left/right
    (`carLane = clamp(carLane ± 1, 0, 3)`). Lane changes are **instantaneous** (snap),
    not animated slides — simpler and robustly correct. (A short CSS-style tween is
    optional but not required; if added, collision still uses the snapped lane.)
  - `ArrowUp` / `ArrowDown`: **optional** speed nudge. Up increases `obstacleSpeed` by
    a small step (e.g. +15 px/s, capped at the max); Down decreases it (floored at the
    current difficulty's base). This is a nice-to-have per the Team Lead plan ("nudge
    speed optionally"); it must not let the player make the game trivially easy (floor
    the speed at the score-derived base, and the cap stays 360).
  - `Space` or any arrow: in `"start"` → begin playing; in `"over"` → reset and begin
    a new run.
  - **`preventDefault()`** on `ArrowUp/Down/Left/Right` and `Space` so the page does
    not scroll.
- `keyup`: not strictly needed for lane-snap controls (each press = one lane move),
  but if Up/Down speed-nudge is implemented with held-key acceleration, track key state
  in a `keys` map and clear it on `keyup` and on `window.blur` (so a stuck key doesn't
  run the player off after alt-tab).
- Recommended (not required): also accept `WASD` as aliases for arrows, since it costs
  one extra `||` per key and helps players on laptop layouts. If added, document it in
  the start overlay.

### Restart
- Restart re-initializes: `carLane` back to a starting lane (e.g. lane 1, left-center),
  clear all obstacles, reset `score`, `obstacleSpeed`, `spawnInterval`, `spawnTimer`,
  set `state = "playing"`. **Do not** clear the high score (it persists in localStorage).

---

## 4. Scoring and Difficulty

### Score
- Score is **time-based**: while `state === "playing"`, `score += dt * 10` (so roughly
  +10 points per second survived). Displayed as `Math.floor(score)`.
- Drawn on canvas, top-left or top-center, in a readable color with enough contrast
  against the road (e.g. white text, slight shadow). Font: a safe web-safe stack
  (`monospace` or `"Trebuchet MS", sans-serif`), size ~20px.

### High score
- Stored in `localStorage` under key `"carGameHighScore"`.
- On entering Game Over: if `Math.floor(score) > highScore`, update `highScore` and
  write it back to localStorage (wrap the write in `try/catch` — localStorage can be
  unavailable in private mode / file:// sandboxes; failure must not crash the game).
- On load: read the stored high score (default 0 if missing or unparseable, also
  try/catch). Display it next to the current score (e.g. "HI: 123") during play and on
  the Game Over overlay.

### Difficulty curve
- `spawnInterval = max(0.45, 1.1 - score * 0.01)` (in seconds).
- `obstacleSpeed = min(360, 140 + score * 0.6)` (px/s).
- Both derive from `score`, so they ramp smoothly as the player survives longer. The
  caps ensure the game stays possible: at max speed (360 px/s) and min interval (0.45s),
  an obstacle takes ~1.67s to traverse the 600px screen, and spawns every 0.45s, so
  roughly 3–4 obstacles on screen at once across 4 lanes — still leaving an escape.

---

## 5. Accessibility and Robustness

- **Responsive canvas:** CSS scales the 400×600 canvas to fit the viewport while
  keeping aspect ratio (e.g. `max-width: 100%; height: auto;` and centered via flex).
  The internal drawing buffer stays 400×600; only the displayed size changes. Logic
  never reads CSS pixel size — it always uses the 400×600 buffer, so resizing cannot
  break collision or input math.
- **Keyboard focus:** listener is on `document`, so the game is keyboard-focusable
  immediately on load without clicking. Good for the "preventDefault on arrows" to
  actually take effect globally.
- **No page scroll on arrows/Space** via `preventDefault()`.
- **Tab-switch safety:** clamp `dt` to 0.05s; clear held keys on `window.blur`.
- **localStorage safety:** all reads/writes try/catch; the game runs fine with no
  persistence (high score just stays 0 for the session).
- **No external dependencies:** the file must work from `file://` with no network. QA
  tests for absence of `<link>`, external `<script src>`, and any URL in the source.
- **No alerts/prompts:** all UI (start, game over, score) is drawn on the canvas or in
  inline DOM overlays styled by the inline `<style>`. No `alert()`/`confirm()`.

---

## 6. Inline CSS (summary for the Developer)

Minimal, just enough to center the canvas and make it look intentional:

- `html, body { margin:0; height:100%; background:#0d1017; }`
- `body { display:flex; align-items:center; justify-content:center; }` (centers canvas)
- `canvas { display:block; max-width:100%; max-height:100vh; height:auto;
  image-rendering:auto; }` (keeps aspect ratio, scales down on small screens)
- Overlay text styling (if using inline DOM overlays for start/end screens) OR draw
  overlays directly on the canvas (simpler, fewer moving parts — **recommended**:
  draw the start and game-over text on the canvas itself so there's literally one
  element: the canvas).

**Recommendation:** draw *everything* (including the "Press Space to start" and
"Game Over" text) on the canvas, so the DOM stays `<canvas>` + `<script>` only. This
minimizes the QA surface and matches "one canvas, all code inline."

---

## 7. QA Acceptance Criteria

The Developer writes tests against the **public file seam** (the committed `index.html`
loaded in a headless browser, or parsed as text). Each criterion maps to a test:

1. **File loads with no external dependencies.**
   - `index.html` exists at repo root; parses as HTML5 (`<!DOCTYPE html>` present).
   - Contains exactly one `<canvas id="game">`.
   - Contains **no** `<link>`, no `<script src=...>`, no `<img>`, and no `http://` /
     `https://` URL strings (grep the source). Must run from `file://` with network off.
2. **Arrow key handlers are wired.**
   - A `keydown` listener on `document` (or `window`) handles `ArrowLeft`/`ArrowRight`
     (and optionally `ArrowUp`/`ArrowDown`, `Space`).
   - `preventDefault()` is called for arrow keys and Space (verified by simulating a
     keydown and checking the default was not scrolled, or by checking the listener
     code path).
3. **Car moves and is clamped to bounds.**
   - Pressing `ArrowLeft` from the leftmost lane does nothing (stays lane 0);
     `ArrowRight` from the rightmost lane does nothing (stays lane 3).
   - Pressing `ArrowRight` from lane 0 moves the car one lane right (x increases by
     one lane width). Repeated presses move across lanes but never beyond `[0,3]`.
   - The car's x is always within `[0, 400-40]` (i.e. fully on the canvas).
4. **Collision ends the game.**
   - When an obstacle overlaps the player's rectangle, the game transitions to the
     Game Over state (loop stops advancing obstacles / car; the car cannot move).
   - This is verifiable by spawning an obstacle in the player's lane and stepping the
     loop, then asserting the state is `"over"` and no further movement occurs.
5. **Restart works.**
   - From Game Over, pressing `Space` (or an arrow) resets to a fresh playing state:
     obstacles cleared, score back to 0, car at the start lane, `state === "playing"`.
6. **Score is shown and high score persists.**
   - While playing, a numeric score is rendered (visible as canvas pixels / readable
     from the draw call or from the exposed score value).
   - Score increases over survived time (assert score-after-2s > score-at-0).
   - After a game over, the high score is written to `localStorage["carGameHighScore"]`
     (and read back on load). Clearing localStorage resets the displayed high score to 0.
7. **(Robustness) No console errors on load and during a short play session.**
   - Loading the file in a headless browser produces no `console.error` and no
     uncaught `pageerror`. A 2-second simulated play session (press a couple of arrows)
     produces no errors.

### Test seam for QA
The Developer should expose a **debug hook** `window.__GAME__` (only present, harmless,
and not required for play) exposing at least: `start()`, `step(dt)` (advance one frame
manually), `setKey(name, down)` (simulate a key), and `snapshot()` returning
`{ state, carLane, carX, carY, score, highScore, obstacles: [{lane,y}], obstacleSpeed,
spawnInterval }`. This lets QA drive the deterministic tests above without relying on
real rAF timing. (The prior hello-world tests asserted the static file; here QA needs a
runtime hook because behavior is dynamic.)

---

## 8. Open Questions (for Team Lead → CEO)

1. **Port for the static server.** Team Lead recommended 8080. I recommend **8080**
   (non-privileged, common for static dev servers, unlikely to collide). CEO to confirm;
   DevOps waits on this before going live.
2. **Up/Down speed nudge.** The Team Lead plan allows Up/Down to nudge speed optionally.
   **Recommended:** implement it as a minor held-key acceleration within the
   `[base, cap]` band so it can't trivialize the game. If the CEO wants the simplest
   possible controls (Left/Right only), drop Up/Down entirely.
3. **WASD aliases.** **Recommended:** include them (cheap, helpful). CEO preference?
4. **Scope vs. the existing `workspace/balap-mobil-2d.html` prototype.** That prototype
   is a far more elaborate top-down Micro-Machines racer (AI cars, Catmull-Rom track,
   3 laps, standings table). It does **not** match the CEO's stated request ("game mobil
   2D, kontrol keyboard panah, 1 html, running di server") nor the Team Lead's plan
   (endless vertical lane-dodger). **Recommended:** ship the simpler lane-dodger this
   spec describes, as planned; treat the prototype as a throwaway spike. If the CEO
   actually wanted the elaborate racer, that is a different, larger task and needs its
   own spec/plan. (I am proceeding on the lane-dodger assumption per the Team Lead plan.)
5. **Restart trigger.** Spec allows Space *or* any arrow to restart from Game Over.
   **Recommended:** Space to restart (arrows to start a new run could be confusing if
   the player is mashing Left/Right). CEO preference?

I proceed on the recommended answers above; the Team Lead/CEO can override before or
after the Developer builds.

---

## 9. Files Touched

- **Overwrite:** `/home/serverbot/aidev/index.html` (currently the hello-world file —
  per the assignment, reuse this path).
- **Create (this spec):** `docs/superpowers/specs/2026-10-07-2d-car-game-design.md`.
- **No other files.** The Developer writes only `index.html`; QA writes a test file
  (e.g. `test_car_game.py` or `verify.js` in a headless browser) against the public seam.
- The existing `workspace/balap-mobil-2d.html` is **not** referenced by this build; it
  remains as a prior spike artifact and should not be served or shipped.

---

## Skills applied
- brainstorming: Classified the task as bounded (single self-contained file, scoped by the Team Lead plan), wrote this short design artifact with files-touched, controls, and QA definition, and flagged scope-vs-prototype as an open question rather than silently expanding scope.
- writing-plans: Not separately invoked — the Team Lead owns the plan/handoff; this spec is the design artifact the Developer builds from. (Plan-ownership boundary respected.)
- domain-modeling: Defined and disambiguated the core domain terms inline (lane, carLane, obstacle, state machine: start/playing/over, score vs highScore) so the Developer and QA share one vocabulary; no GLOSSARY.md created because the domain is small and self-contained in this spec.
- codebase-design: Applied the deep-module lens — the "module" is the single file with one canvas element as its interface; lane-snap movement makes bounds trivially correct (clamp on an integer 0–3); debug hook `window.__GAME__` is the test seam so QA tests through the same surface players use; deletion test confirms one self-contained file earns its keep (complexity vanishes if removed, but reappears across N callers if split — so keep it one file).
- grilling: Surfaced five frontier questions where the assignment or prior artifacts leave real choices (port, Up/Down nudge, WASD aliases, scope-vs-prototype, restart trigger) with recommended answers, proceeding on them and flagging for CEO override rather than silently assuming.
