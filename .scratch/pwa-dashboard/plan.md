# PWA Dashboard with Realistic Graphics — Plan

Phone-installable dashboard for RoomSense, built to `.kiro/specs/roomsense-occupancy-tool/` (requirements.md, design.md). Requirement numbers below (R13.4 and so on) refer to that spec.

Goal: a responder opens the app on a phone and within 5 s sees a convincing 3D floor plan of the building, the room to search first, and how much to trust each room. "Realistic" means the building looks real: measured walls, doors, nodes and lighting. The occupancy data must stay honest: room-level only, and never "empty".

---

## 0. Decisions needed before building

These are places where a phone PWA conflicts with the current spec. Each has a recommendation. Record the outcome in `CONTEXT.md` and amend the spec in Kiro.

| # | Conflict | Spec says | Recommendation |
|---|---|---|---|
| D1 | Display device | No tablet; the demo runs on the laptop screen (Intro decision 2, R10.2) | Phone PWA is the responder view. The laptop keeps the same app in a browser as the installer/presenter view. The layout is phone-first and scales up to the laptop. |
| D2 | Network exposure | Hub binds to `localhost` only. A second device is a [Could] and read-only (design, Security note) | Hub also listens on the laptop's Windows Mobile Hotspot interface (5 GHz, WPA2, usually `192.168.137.1`). Every HTTP and WS call requires a **pairing token**. Responder actions (mark searched, end incident) are allowed from the phone with the token. The alarm trigger stays on the laptop landing page (R16.1). |
| D3 | Secure context | Not covered | **Decided: iPhone, so mkcert.** A PWA's service worker and install only work over **HTTPS** (or `localhost`). Use an mkcert local CA with the cert SAN covering `192.168.137.1` and `localhost`, and install and fully trust the root CA on the iPhone (steps in section 5). |
| D4 | Rooms on the floor plan | Spec: 2-room demo (R1, R2). CONTEXT: 1 real room (13 ft x 9 ft 4 in) plus rooms labeled SIMULATED | Floor plan has R1 = the measured conference room (live) and R2 (live if the second link works). Add 2–4 more rooms on a second floor, each labeled **SIMULATED** (R10.5). This makes floor tabs and ranking worth showing. |
| D5 | What "realistic" covers | — | Realistic **architecture** (walls, doors, furniture outlines, nodes, lighting). **No** person figures, footprints, heat blobs, or animated smoke. Any of those would imply sub-room position or a fire we did not test (AGENTS: do not overclaim; CONTEXT: never fake smoke). |

---

## 1. Hard constraints the graphics must satisfy

These come from the spec and AGENTS.md. Each one becomes a test (section 7).

1. **Four states only:** `MOTION`, `POSSIBLE`, `UNKNOWN`, `NO DETECTION`. Never "empty" or "clear" (R8.2, R12.1). NO DETECTION must **not** be green or look "safe".
2. **Color is never the only signal.** Every state has an icon, a text label and a distinct floor **pattern**, and stays distinguishable in grayscale (R12.1, R12.2).
3. **Room-level only.** Effects are anchored to the room centroid or the whole floor slab, never to a point that looks like a person's position (Privacy rule 3).
4. **Priority is legible:** rank badges match the server's `ranking` array. The client never re-ranks (R9). The top room is identifiable within 5 s of fire mode (R13.3).
5. **Never silently stale:** a stale room shows "last known MOTION, 0:12 ago" (R14.3). If the hub is lost for 5 s, show a full-width banner and grey out every room (R19.8).
6. **Always visible:** disclaimer (R10.3), Recording_Indicator (R15.7), Health_Chip (R19.4), Simulated_Data_Badge when `simulated` (R10.5).
7. **Touch targets ≥ 56 px** (R12.3). No typing in fire mode (R13.8). Mark searched in ≤ 2 taps (R13.4).
8. **Crew marker** uses its own icon and the tag label, never a state color (R26.1). Low confidence shows "Near R1 / R2" or "Between rooms", never one room (R25.5, R25.6).
9. **Privacy on the phone:** the service worker caches the **app shell only**. No room states, crew positions or incident data go to Cache Storage, IndexedDB or localStorage. Occupancy lives only in JS memory and is dropped on End incident (R15, R21.3).
10. **Fully offline, no CDN:** all JS, fonts and textures are bundled (R10.1, design Web stack).
11. **No third-party marks:** no fire-department insignia, Star of Life, or brand icons. Draw our own icons. Font: Atkinson Hyperlegible (OFL), bundled.

---

## 2. Architecture

```
hub (FastAPI) ──HTTPS/WSS + token──► PWA
                                      │
              ws/messages.ts ─► store (room_states, health, crew, recording, link status)
                                      │
              scene/model.ts   (PURE: floorplan.json + store ─► SceneModel)
                     │                         │
        render3d/ (three.js, isometric)   render2d/ (SVG, top-down)
          main view on capable phones       fallback, snapshot inset, tests,
                                            reduced-motion / low-power mode
                     │
        ui/ (Preact): header chips, floor tabs, priority list,
                      room bottom sheet, banners, pairing screen
```

- **One pure view model, two renderers.** `buildSceneModel(floorplan, state, now)` returns per-room descriptors `{roomId, polygon, state, label, icon, pattern, rank, confidence, lastSeenText, staleText, searched, simulated, crew[], annotations[]}`. The 3D and 2D renderers only draw descriptors and make no decisions. This keeps the safety logic in one testable place, matching the project's pure-function convention.
- **Server is the source of truth.** The client never computes state, confidence or rank. It only formats them, for example turning `last_seen` into "Motion last seen 0:42 ago".
- **Labels are DOM, not WebGL.** State labels, confidence and rank badges are HTML overlays (three.js `CSS2DRenderer`) pinned to room centroids. They stay crisp, can be tapped, can be read by a screen reader, and can be tested.

### Stack

| Need | Choice | Why |
|---|---|---|
| Build | Vite + TypeScript | Fast; outputs static files the hub serves from one origin |
| UI chrome | Preact (~4 KB) | Light, close to "framework-light" |
| 3D | three.js (npm, bundled) with `OrthographicCamera` and `CSS2DRenderer` | Mature, runs on phone GPUs, no CDN |
| PWA | `vite-plugin-pwa` (Workbox), shell precache only | Manifest, icons and SW with a runtime-cache allow-list of **nothing** |
| Tests | Vitest + fast-check (PBT, mirrors the Hypothesis approach), Playwright with iPhone and Pixel emulation | Unit, property and screenshot tests |
| Mock hub | `tools/mock_hub.py` (FastAPI) emitting the exact WS shapes from design.md | UI work doesn't wait on firmware. Sets `simulated: true` |

### Repo layout

```
dashboard/
  public/  manifest icons (own art), fonts/AtkinsonHyperlegible-*.woff2
  src/
    floorplan/ load.ts types.ts       # fetch + validate /api/floorplan
    ws/        client.ts messages.ts  # typed shapes from design.md; reconnect; token
    scene/     model.ts patterns.ts palette.ts   # PURE
    render3d/  scene.ts walls.ts floors.ts links.ts crew.ts camera.ts
    render2d/  svg.tsx
    ui/        Header.tsx FloorTabs.tsx PriorityList.tsx RoomSheet.tsx Banners.tsx Pair.tsx
  tests/       model.prop.test.ts palette.test.ts privacy.test.ts e2e/*.spec.ts
hub/static/    # vite build output, served by FastAPI
hub/config/floorplan.json   # hand-edited by the team; served at GET /api/floorplan
tools/mock_hub.py           # serves the same floorplan.json
```

---

## 3. Floor plan data (`hub/config/floorplan.json`)

**Decided:** the team writes the floor plan by hand in this JSON file. There is no floor-plan editor. FastAPI serves it at `GET /api/floorplan` (token required). The app fetches it at startup and keeps it in memory, and three.js and the SVG renderer draw from it. To change the layout at the venue, edit the file and reload the app; no rebuild is needed.

All values are in meters, with the origin at the bottom-left of each floor. Room `id`s must match the hub's room IDs (`R1`, `R2`, …). The app validates the file on load (closed polygons, door offsets within the wall, every node's room exists, ids unique) and shows a plain-language error instead of drawing a broken plan.

```json
{
  "floors": [{"id": "F1", "name": "Floor 1", "rooms": [
    {"id": "R1", "name": "Conference", "live": true,
     "polygon": [[0,0],[3.96,0],[3.96,2.84],[0,2.84]],
     "doors": [{"wall": "W", "offset": 0.0, "width": 0.91, "swing": "in"}],
     "furniture": [{"kind": "table", "rect": [1.2,0.9,1.8,1.0]}],
     "crewSlot": [0.4, 0.4]}
  ]}],
  "nodes": [
    {"id": "TX1", "role": "TX", "room": "R1", "pos": [3.35, 0.0], "h": 1.0},
    {"id": "RX1", "role": "RX", "room": "R1", "pos": [3.35, 2.84], "h": 1.0}
  ],
  "links": [{"tx": "TX1", "rx": "RX1"}]
}
```

- R1 uses the measurements in CONTEXT.md: 13 ft x 9 ft 4 in, a 3 ft door in a corner of the short wall, nodes about 2 ft from the entry wall. Fill in furniture and door swing (CONTEXT TODO) once measured.
- `crewSlot` is a fixed spot per room where crew markers stack. It is explicitly not a measured position.
- Node IDs and roles are installation data, not device identifiers. MAC addresses never appear in the floor plan or in the app.

---

## 4. Visual design

### 4.1 Scene and "realism" budget

- **Camera:** orthographic isometric (about 35° tilt, 45° yaw) so rooms never hide behind each other. A 2-finger gesture rotates in 90° steps only. Pinch zooms and is clamped. Double-tap a room to frame it.
- **Walls:** extruded from polygons, 0.12 m thick, cut away to **1.0 m height** (dollhouse view) so floors stay visible. Matte off-white walls with a darker top cap so the plan reads like an architectural drawing. Door openings are real gaps with a thin door leaf and a swing arc on the floor.
- **Lighting:** one `HemisphereLight` plus one `DirectionalLight` with a single 1024² shadow map and baked contact shadows (a gradient texture strip at the base of each wall). That gives most of the ambient-occlusion look without SSAO, which costs too much on phones.
- **Furniture:** low-poly grey blocks with low contrast, so they never compete with state colors.
- **Nodes:** small rounded-box devices on the walls at their real height, with a status LED (green ok / amber degraded / dark plus "!" offline). Node status is health data, so green is acceptable there, unlike for room states.
- **Links:** TX→RX beams drawn as thin tubes with dashes moving at a speed proportional to `measured_pps`. `tx_dead` gives a broken red dashed beam plus a fault icon. An offline RX makes the beam disappear and shows "!" at the node. This shows how the sensing works without implying positions.
- **Building context:** a ground plane with a soft vignette and a faint 1 m grid. A floor selector shows other floors as stacked ghost slabs.
- **Off-limits:** person figures, footprints, heatmaps, trails inside a room, smoke or fire particles.

### 4.2 State encoding (the core of the graphics)

| State | Floor fill (dark theme) | Pattern (grayscale-safe) | Icon + label | Motion (off if `prefers-reduced-motion`) |
|---|---|---|---|---|
| MOTION | high-saturation red-orange `#FF4D2E` | solid, brightest luminance | wave glyph + **MOTION** | rings expand from the **room centroid** about every 1.2 s, clipped to the room polygon |
| POSSIBLE | amber `#FFB020` | diagonal hatch, 45° | hollow-person-outline-with-? glyph + **POSSIBLE** | slow 3 s edge glow. Do not make it look like breathing. |
| UNKNOWN | violet-grey `#8A7FB8` | cross-hatch plus fine static noise | ? glyph + **UNKNOWN** | none (static, so it can't look "active"); shows "last known X, 0:12 ago" |
| NO DETECTION | slate `#3A4250`, outline only | sparse dots, darkest | dash glyph + **NO DETECTION** | none; sub-label "Still needs a sweep" |

- Check luminance order for grayscale: MOTION > POSSIBLE > UNKNOWN > NO DETECTION, with pattern as a second channel. Verify with an automated grayscale screenshot diff (section 7).
- Patterns are procedural `CanvasTexture`s (no image assets), tiled in world units so hatch density is the same in every room.
- **Searched:** the floor drops to 35% opacity, a ✓ **SEARCHED** chip appears, and the rank badge moves to the end (R13.4, R9.5). Use the word "Searched", never "Clear".
- **Uncalibrated:** UNKNOWN plus a ⚠ "Uncalibrated" chip (R1.5, R7.4).
- **Simulated room:** diagonal repeating "SIMULATED" text baked into the floor texture, plus a SIMULATED chip on the label (R10.5).
- **Low confidence:** the label shows the band and percent ("LOW 34%"). The floor fill saturation drops in steps (high 100%, med 75%, low 50%) so trust is visible at a glance. The pattern stays intact so the state is still readable.
- **Rank badge:** a large numeral disc (1, 2, 3…) on each flagged room. Rank 1 gets a white halo ring so it is the first thing the eye lands on (R13.3).

### 4.3 Crew markers (Should)

- Shape: an upright chevron "pin" in white with a black outline and the tag label ("E1"). It uses no state color, so the crew palette is `{#FFFFFF, #111111}` only (R26.1). Stacked at the room's `crewSlot`.
- Hollow outline plus "Last heard R2, 0:40 ago" after 10 s silent. It stays where it was last heard and never moves on its own (R25.7).
- Low confidence: no marker inside a room. Instead a chip on the shared wall or door between the candidate rooms reading "E1 · Near R1 / R2" or "E1 · Between rooms" (R25.5, R25.6).
- "Motion · responder present" and "recent motion may be responder" are text annotations on the label only. They never change the fill (R27.1–27.3).

### 4.4 Phone layout (portrait first)

```
┌──────────────────────────────┐
│ ● Recording (alarm)   2 faults ▾│ header: Recording_Indicator + Health_Chip (56 px)
│ Decision support only — does   │ disclaimer, always visible, 2 lines max
│ not replace a full search      │
│ [SIMULATED DATA]  [SIMULATED TRIGGER]
├──────────────────────────────┤
│ [F1 •2] [F2 •1]               │ floor tabs with attention + crew counts (R13.5, R26.3)
│                                │
│        3D isometric plan       │ ~55% of screen height
│                     ┌──────┐   │
│                     │AT    │   │ alarm-time snapshot inset (2D SVG) (R14.1)
│                     │ALARM │   │ tap to swap with the live view
│                     └──────┘   │
├──────────────────────────────┤
│ ① R1 Conference  MOTION 86%  ✓│ priority list = bottom sheet, flagged rooms only,
│ ② R3 Office SIM  POSSIBLE …  ✓│ server order; ✓ = mark searched (tap + confirm)
│ ③ R2 Storage     UNKNOWN 0:12 ✓│ drag up for full list
└──────────────────────────────┘
```

- Tapping a room on the map or in the list opens a **room bottom sheet**: state, confidence, last activity, alarm-time state, link health, Edge/Hub source badge, crew present, and "Mark searched" (R13.6, R37.2).
- Landscape (and the laptop) puts the list on the right as the side list the spec describes (R13.2).
- End incident is laptop-only: tap, then a confirm sheet (R15.11). The phone doesn't show the button.
- When all flagged rooms are searched, show the banner "No detection rooms still require a sweep" (R13.7).
- Normal (IDLE) mode on the phone shows the building with link and node health only. No occupancy is shown because the hub sends none in IDLE (R15.2). Installer controls (calibration, test mode) are **not** on phone screens (R18.5). They stay on the laptop.
- Use `env(safe-area-inset-*)`, `100dvh`, and `theme-color` switching to red when an alarm is active.

### 4.5 Fire-mode entry (the demo moment)

1. A `room_states` message arrives with `system_state: ALARM_ACTIVE`.
2. Within 300 ms: the header turns red, "Recording (alarm)" shows, and the snapshot inset freezes from the first ALARM_ACTIVE message. There is no haptic feedback because iOS Safari doesn't support `navigator.vibrate`, so the alert is visual only, with a 1 s full-screen red flash (skipped under reduced motion).
3. The camera eases about 600 ms to frame all flagged rooms. Rank 1 gets its halo and the priority sheet opens to the first 3 rows.
4. Request the Screen Wake Lock (best effort; re-request on `visibilitychange`). It works in a home-screen PWA from iOS 18.4. On older iOS, set Auto-Lock to Never on the demo phone.

---

## 5. Connectivity, PWA and security

- **iPhone gotcha:** a home-screen PWA on iOS has **separate storage from Safari**. A token saved while the page is open in Safari doesn't carry over to the installed app, and scanning a QR code with the Camera app always opens Safari. So pairing must happen **inside the installed app**.
- **Pairing (in normal mode, done once):**
  1. In Safari, open `https://192.168.137.1:8443` and use Share → Add to Home Screen. The laptop dashboard can show this URL as a QR code.
  2. Open the installed app. With no token, it shows a pairing screen.
  3. The laptop shows a **6-digit pairing code**, valid for 2 minutes and single-use, displayed only on `localhost`. Typing it on the phone is allowed because this is normal mode, not fire mode.
  4. The app sends `POST /api/pair {code}`. The hub rate-limits attempts (5 per minute) and returns a long random token. The app stores the token in `localStorage`; the token isn't occupancy data, so this is allowed.
- **Token lifetime:** the hub keeps the token in a git-ignored `hub/config/secrets.json`, so restarting the hub doesn't un-pair the phone mid-demo. Add a "Revoke phones" button on the laptop. The WS sends `{"type":"auth","token":...}` as its first message, and HTTP calls use `Authorization: Bearer`.
- **Phone actions:** the phone can mark rooms searched. **End incident and the alarm trigger stay on the laptop**, so an accidental tap can't wipe the Incident_Record in front of judges.
- **WS client:** exponential reconnect with 0.5 s → 5 s backoff. Reconnect immediately on `visibilitychange` and `online`, since iOS kills sockets in the background. Track `lastMessageAt`. After 5 s with no message, raise the hub-lost banner and set every room to a "STALE — last known X" overlay (R19.8). The app never shows cached state as live.
- **Service worker:** Workbox precaches only the shell (HTML, JS, CSS, fonts, icons). `navigateFallback` points to the shell. There are **no** runtime caching routes. `/api/*` and `/ws` are never cached. On End incident (`system_state` returns to IDLE), the in-memory store is cleared.
- **Manifest:** `display: standalone`, `orientation: any`, dark `background_color`, own-art icons (192, 512, maskable, plus `apple-touch-icon`).
- **Hub changes (small):** serve `hub/static` with an SPA fallback; serve `GET /api/floorplan` from `hub/config/floorplan.json`; add a token dependency on every route and the WS; add `POST /api/pair` and a laptop-only (`localhost`) pairing-code endpoint; add an HTTPS listener with the mkcert cert (paths in a git-ignored `.env`, with `.env.example` committed). Keep `.pem` files and `secrets.json` in `.gitignore`.
- **mkcert on the iPhone (do this before the event; it takes about 10 minutes):**
  1. On the laptop: `mkcert -install`, then `mkcert -cert-file hub/certs/hub.pem -key-file hub/certs/hub-key.pem 192.168.137.1 localhost 127.0.0.1`.
  2. Send `rootCA.pem` (from the folder `mkcert -CAROOT` prints) to the iPhone by AirDrop or email, then open it.
  3. Settings → General → VPN & Device Management → install the profile.
  4. Settings → General → About → Certificate Trust Settings → turn on full trust for the mkcert root. **If you skip this step, Safari still shows a warning and the service worker won't register.**
  5. Check that `https://192.168.137.1:8443` opens in Safari with no warning.
  6. If the hotspot IP isn't `192.168.137.1`, check it with `ipconfig` and reissue the cert.
- **iOS WebSocket behavior:** iOS suspends a backgrounded PWA and drops its socket. On `visibilitychange` → visible, reconnect and show "Reconnecting…" until the first fresh message. The 5 s hub-lost rule still applies.
- **Radio hygiene:** set the Windows hotspot to the **5 GHz** band so phone traffic stays off the 2.4 GHz sensing channel (design R26.4 note).

---

## 6. Build phases (one person, about 5 h; cut lines marked ✂)

| Phase | Time | Output | Done when |
|---|---|---|---|
| P0 Scaffold | 0:00–0:30 | Vite + TS + Preact. `messages.ts` typed from design.md. `mock_hub.py` replaying a scripted incident (walk in, R1 MOTION → POSSIBLE, RX2 offline → UNKNOWN, tag E1 moves, searched marks). `demo.floorplan.json` | Mock WS messages logged in the browser |
| P1 Model + 2D | 0:30–1:30 | `scene/model.ts` (pure), palette and patterns, SVG renderer, header chips, disclaimer, priority list, room sheet | The whole fire-mode flow works in 2D on the laptop. **This is the safety net and is demo-able on its own.** |
| P2 Phone + PWA | 1:30–2:15 | Hub HTTPS + `/api/floorplan` + token + static serving, in-app pairing-code screen, SW, manifest, apple-touch-icon, hub-lost banner. (mkcert root CA already trusted on the iPhone, done before the event.) | Installed to the iPhone home screen, paired, works over the hotspot, still paired after a hub restart, banner appears when the hub is killed |
| P3 3D scene | 2:15–3:45 | Walls with door cutouts, floors with pattern textures, lighting and contact shadows, nodes, link beams, CSS2D labels, rank halo, camera framing and gestures | 60 fps on the phone with the mock incident. ✂ **At 3:45, if it is under 30 fps or labels are illegible, ship the 2D renderer with styled walls and drop 3D to a "3D view" toggle.** |
| P4 Fire-mode polish | 3:45–4:30 | Fire-mode entry sequence, snapshot inset, floor tabs with counts, crew markers and near/between chips, searched dimming, all-searched reminder, wake lock and haptics | Matches the demo video script steps 2–4 |
| P5 Tests + capture | 4:30–5:00 | Property tests, privacy and banned-word tests, Playwright grayscale screenshots, screen recordings for the video | CI green; video clips captured |

✂ **Overall cut order:** crew-marker chips → floor-2 simulated rooms → snapshot inset becomes a toggle → 3D (keep 2D). Never cut: disclaimer, recording indicator, health chip, hub-lost banner, stale display.

### Performance budget (mid-range phone)

- `renderer.setPixelRatio(Math.min(devicePixelRatio, 2))`. Render on demand: only redraw when a message arrives, an animation is active, or a gesture is in progress. Pause when `document.hidden`.
- Fewer than 50 draw calls: merge walls per floor into one `BufferGeometry` and reuse shared materials.
- Total JS bundle under 350 KB gzipped (three.js tree-shaken ≈ 150 KB). First paint under 1.5 s from cache.
- If the WebGL context is lost or `failIfMajorPerformanceCaveat` fails, fall back to 2D automatically.

---

## 7. Tests (feed into the Kiro spec as properties)

**Property tests (fast-check, ≥ 100 runs, on `scene/model.ts`):**
- P-UI1: for any `room_states` message, every descriptor's label is one of the four labels, and no user-visible string matches `/\b(empty|clear(ed)?|safe)\b/i`.
- P-UI2: the rendered priority order is identical to the server's `ranking` filtered to flagged rooms. Searched rooms come last.
- P-UI3: for any crew input, the marker color is not in the state palette, and low confidence never produces a single-room marker.
- P-UI4: any room with `stale: true` gets a descriptor with stale text and the UNKNOWN treatment.
- P-UI5: if `now − lastMessageAt ≥ 5 s`, every descriptor is marked stale and the hub-lost banner is on.
- P-UI6: state luminance order and patterns are pairwise distinct (palette unit test using the WCAG relative-luminance formula).

**Privacy tests:**
- The built `sw.js` contains no runtime-caching routes. A Playwright run through a full incident ends with empty Cache Storage (apart from the precache), empty IndexedDB, and `localStorage` holding no room or crew keys.
- No string resembling a MAC address (`/([0-9a-f]{2}:){5}/i`) appears in the bundle or the floor plan.

**Playwright (iPhone 14 and Pixel 7 emulation):**
- A screenshot per state, converted to grayscale. Assert that the pairwise mean pixel difference over the room region exceeds a threshold (R12.2).
- All interactive elements have a bounding box ≥ 56×56 (R12.3).
- Mark searched takes at most 2 taps (R13.4). A floor switch takes 1 tap (R13.5).

---

## 8. Kiro usage (for the "Best Use of Kiro" score)

- **Spec:** paste sections 0–7 into Kiro to generate `.kiro/specs/pwa-dashboard/` (requirements → design → tasks). Reference the parent spec's requirement IDs rather than duplicating them.
- **Steering:** add `.kiro/steering/ui.md` with the palette, the state encoding table, the banned words, "no person figures or smoke", and the 56 px rule.
- **Hooks:** (1) on save in `dashboard/src/**`, run Vitest property tests; (2) on save, grep UI strings for banned words and MAC-like patterns; (3) on build, assert the SW has no runtime caching.
- **Log** each of these in CONTEXT.md under Kiro Plan & Usage Log.

---

## 9. Open questions

- D1, D2, D4, D5 above (D3 decided: iPhone + mkcert).
- Which iOS version is the demo phone on? 18.4 or later gets wake lock in the installed app.
- Does RX1/Annunciator stay the laptop-free display (R36)? The phone depends on the laptop hub, so the laptop-unplug demo still relies on the Annunciator.
- Should the built `hub/static` be committed so judges can run without Node? Recommend yes, rebuilt in P5.
