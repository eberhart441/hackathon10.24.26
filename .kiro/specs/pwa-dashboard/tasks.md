# Implementation Plan: PWA Dashboard

## Overview

Build order follows plan section 6: scaffold and typed contracts first (P0), then the hub web layer and mock incident, then a demo-able 2D safety net on the laptop (P1), then phone pairing, HTTPS, and the PWA shell (P2), then the 3D renderer (P3), then fire-mode polish (P4), then end-to-end tests, docs, and Kiro artifacts (P5).

Cut order (plan section 6), marked on the affected sub-tasks: **cut 1** crew-marker chips, **cut 2** floor-2 simulated rooms, **cut 3** snapshot inset becomes a toggle, **cut 4** 3D renderer (keep 2D). Optional (`*`) marks only test sub-tasks and these cuttable features. The disclaimer, Recording_Indicator, Health_Chip, hub-lost banner, and stale display are required.

All "Done when" commands run from the repository root in PowerShell. The repo path contains spaces, so keep commands relative to the root.

## Tasks

- [x] 1. Scaffold, pinned dependencies, typed contracts, and floor plan
  - [x] 1.1 Scaffold the dashboard project with exact-pinned dependencies
    - Create `dashboard/package.json` (scripts: `build` = `tsc --noEmit && vite build`, `test` = `vitest --run`, `e2e` = `playwright test`), `dashboard/tsconfig.json` (strict), `dashboard/vite.config.ts` (Preact preset, `build.outDir: "../hub/static"`, `emptyOutDir: true`), `dashboard/vitest.config.ts` (jsdom), `dashboard/index.html`, `dashboard/src/main.tsx`, `dashboard/src/app.tsx` (placeholder showing the disclaimer)
    - Install with `npm install --save-exact`: vite, typescript, preact, @preact/preset-vite, three, @types/three, vite-plugin-pwa, vitest, fast-check, jsdom, fake-indexeddb, @playwright/test; commit `package-lock.json`
    - _Requirements: 23.1, 18.1_
    - Done when: `npm --prefix dashboard ci; npm --prefix dashboard run build; npm --prefix dashboard run test -- --passWithNoTests` all exit 0 and `Test-Path hub/static/index.html` is True
  - [x] 1.2 Scaffold the hub package with exact-pinned dependencies and git-ignored secrets
    - Create `hub/__init__.py`, `hub/web/__init__.py`, `hub/web/settings.py` (Settings with the defaults in the design table, loaded from `hub/.env` via python-dotenv), `hub/.env.example`, `hub/requirements.txt` with `==` pins for fastapi, uvicorn, python-dotenv, httpx, pytest, hypothesis, `hub/tests/__init__.py`, `hub/tests/conftest.py`
    - Append `hub/.env`, `hub/certs/`, `*.pem`, `hub/config/secrets.json` to `.gitignore`; do not add `.kiro`
    - _Requirements: 4.5, 23.1_
    - Done when: `python -m pip install -r hub/requirements.txt; python -c "import hub.web.settings as s; print(s.Settings.load().port)"` prints `8443` and `Select-String -Path .gitignore -Pattern 'secrets.json'` returns a match
  - [x] 1.3 Add a dependency pin checker
    - Create `tools/check_pins.py` that fails if `dashboard/package.json` has any `^`, `~`, `>`, `<`, `*`, `x`, or `latest` version, or if any `hub/requirements.txt` line lacks `==`; create `tools/__init__.py`, `tools/tests/__init__.py`, `tools/tests/test_check_pins.py`
    - _Requirements: 23.1_
    - Done when: `python tools/check_pins.py` exits 0 and `python -m pytest tools/tests/test_check_pins.py -q` passes
  - [x] 1.4 Implement typed hub messages on both sides
    - Create `dashboard/src/ws/messages.ts` (types and `parseMessage` per the design, label/state consistency check, never throws) and `hub/web/messages.py` (TypedDicts plus `label_for(state)`), both matching the parent design's "Hub: Web Server" shapes
    - _Requirements: 7.1, 7.2_
    - Done when: `npm --prefix dashboard run build` exits 0 and `python -c "from hub.web.messages import label_for; assert label_for('NO_DETECTION')=='NO DETECTION'"` exits 0
  - [x]* 1.5 Write property test for message parsing
    - Create `dashboard/tests/arb.ts` (message arbitraries) and `dashboard/tests/messages.prop.test.ts`
    - **Property 1: Message parsing round-trips and rejects malformed input**
    - **Validates: Requirements 7.1, 7.2**
    - Done when: `npm --prefix dashboard run test -- messages.prop` passes with ≥ 100 runs
  - [x] 1.6 Implement floor-plan types, validator, and the committed F1 floor plan
    - Create `dashboard/src/floorplan/types.ts`, `dashboard/src/floorplan/validate.ts` (rules and plain-language messages from the design), `dashboard/src/floorplan/load.ts` (fetch `/api/floorplan` with Bearer, then validate), and `hub/config/floorplan.json` with F1: R1 Conference 3.96 × 2.84 m, 0.91 m door on wall 3 at offset 0, table block, TX1/RX1 about 0.61 m from the entry wall; R2 sharing R1's east wall; links TX1→RX1 and TX2→RX2; no MAC addresses
    - _Requirements: 6.2, 6.3, 6.5_
    - Done when: `npm --prefix dashboard run build` exits 0 and `python -c "import json;d=json.load(open('hub/config/floorplan.json'));print([r['id'] for f in d['floors'] for r in f['rooms']])"` prints `['R1', 'R2']`
  - [x]* 1.7 Write property test for the floor-plan validator
    - Create `dashboard/tests/arbFloorplan.ts` and `dashboard/tests/floorplan.prop.test.ts`
    - **Property 16: The floor-plan validator accepts valid plans and names every broken rule**
    - **Validates: Requirements 6.3, 6.4**
    - Done when: `npm --prefix dashboard run test -- floorplan.prop` passes
  - [x]* 1.8 Write unit test for the committed floor plan
    - Create `dashboard/tests/floorplan.committed.test.ts`: validates `hub/config/floorplan.json`, checks R1 dimensions and door width, checks any F2 rooms are `simulated: true`, and scans for the MAC-like pattern
    - _Requirements: 6.5, 6.6, 6.7_
    - Done when: `npm --prefix dashboard run test -- floorplan.committed` passes

- [x] 2. Hub web layer core (auth, broadcast, routes)
  - [x] 2.1 Implement auth primitives
    - Create `hub/web/auth.py`: `is_loopback`, `TokenStore` (SHA-256 hashes, atomic writes to `secrets.json`, in-memory local tokens, `hmac.compare_digest`), `PairingManager` (6 digits via `secrets.randbelow`, 120 s TTL, single use, replaces prior code), `RateLimiter` (5 per 60 s sliding window per client); all take an injected clock
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 3.4_
    - Done when: `python -c "from hub.web.auth import PairingManager; import time; c,_=PairingManager(time.monotonic).new_code(); assert len(c)==6 and c.isdigit()"` exits 0
  - [x]* 2.2 Write property test for pairing codes
    - Create `hub/tests/test_pairing_prop.py` (Hypothesis stateful or operation-sequence test with a fake clock)
    - **Property 21: Pairing codes work once, only while current and unexpired**
    - **Validates: Requirements 2.1, 2.2, 2.3**
    - Done when: `python -m pytest hub/tests/test_pairing_prop.py -q` passes
  - [x]* 2.3 Write property test for the pairing rate limiter
    - Create `hub/tests/test_ratelimit_prop.py`
    - **Property 22: Pairing attempts are rate-limited per client**
    - **Validates: Requirements 2.4**
    - Done when: `python -m pytest hub/tests/test_ratelimit_prop.py -q` passes
  - [x]* 2.4 Write property test for token persistence and revoke
    - Create `hub/tests/test_tokenstore_prop.py` using `tmp_path`
    - **Property 23: Phone tokens survive restart and die on revoke**
    - **Validates: Requirements 2.5, 2.6, 2.7**
    - Done when: `python -m pytest hub/tests/test_tokenstore_prop.py -q` passes
  - [x] 2.5 Implement the State_Source interface and broadcaster
    - Create `hub/web/source.py` (`StateSource` Protocol) and `hub/web/broadcast.py` (`redact_for_wire`, `Broadcaster.run` at 1 Hz with injected clock, `publish_now`, per-socket kind `phone`/`local`)
    - _Requirements: 7.7, 14.1, 20.2, 20.3_
    - Done when: `python -c "from hub.web.broadcast import redact_for_wire as r; m=r({'type':'room_states','system_state':'IDLE','rooms':[{'room_id':'R1'}],'ranking':['R1'],'ts':0,'simulated':True}); assert m['rooms']==[] and m['ranking']==[]"` exits 0
  - [x]* 2.6 Write property test for wire redaction and MAC-free broadcasts
    - Create `hub/tests/test_broadcast_prop.py`
    - **Property 25: Broadcasts carry no occupancy in IDLE and no MAC-like strings**
    - **Validates: Requirements 14.1, 6.7**
    - Done when: `python -m pytest hub/tests/test_broadcast_prop.py -q` passes
  - [x] 2.7 Implement the FastAPI app and routes
    - Create `hub/web/app.py` with `create_app(source, settings, clock)`: dependencies `require_laptop` (runs first) and `require_token`; every route in the design table; `/ws` with 5 s auth-first handshake and close 4401; phone sockets ignore `trigger_alarm`/`end_incident`; revoke closes phone sockets; `Cache-Control: no-store` on `/api/*`; static files from `hub/static` with SPA fallback that never covers `/api/*`; `HUB_TEST_FORCE_REMOTE` honored only when all bind hosts are loopback
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 2.7, 3.1, 3.2, 3.3, 3.5, 5.1, 5.2, 5.7, 6.1, 20.1, 20.4, 20.5, 20.6_
    - Done when: `python -c "from hub.web.app import create_app"` exits 0 and `python -m pytest hub/tests -q` passes
  - [x]* 2.8 Write property test for token enforcement on every protected route
    - Create `hub/tests/test_routes_prop.py` (iterate the app's route table; Hypothesis-generated header values)
    - **Property 20: Every protected route rejects unknown tokens**
    - **Validates: Requirements 3.1, 3.5**
    - Done when: `python -m pytest hub/tests/test_routes_prop.py -q` passes
  - [x]* 2.9 Write property test for the laptop-only gate
    - Create `hub/tests/test_laptop_gate_prop.py` (Hypothesis IPv4/IPv6 non-loopback addresses via the ASGI `client` scope, including a valid phone token)
    - **Property 24: Laptop-only actions are refused from non-loopback clients**
    - **Validates: Requirements 5.1, 5.2**
    - Done when: `python -m pytest hub/tests/test_laptop_gate_prop.py -q` passes
  - [x]* 2.10 Write hub example tests
    - Create `hub/tests/test_routes.py`: WS auth-first and 4401 close; exempt routes; mark-searched broadcast within 1 s and 404 on unknown room; `health` at ≥ 1 Hz in IDLE with a fake source; SPA fallback; `/api/unknown` returns 404 not `index.html`; `.gitignore` entries; after an incident only `secrets.json` exists under the temp config dir
    - _Requirements: 3.2, 3.3, 3.5, 4.5, 5.7, 7.7, 20.1, 20.5, 20.6_
    - Done when: `python -m pytest hub/tests/test_routes.py -q` passes

- [x] 3. Mock hub with the scripted incident
  - [x] 3.1 Implement the scripted incident State_Source
    - Create `tools/mock_incident.py`: `ScriptedIncident(plan_rooms, clock)` implementing `StateSource` with the design timeline (R1 MOTION→POSSIBLE, E1 R1→near→R2→silent/hollow, RX2 degraded→offline so R2 is UNKNOWN stale with `last_known_state: "POSSIBLE"`), `alarm_time_state` frozen at t = 0, pure `rank()` mirroring parent R9 with searched last, `simulated: true`, IDLE health-only, End incident resets
    - _Requirements: 21.1, 21.2, 21.3, 21.4, 21.5_
    - Done when: `python -c "from tools.mock_incident import ScriptedIncident"` exits 0
  - [ ]* 3.2 Write property test for mock ranking and states
    - Create `tools/tests/test_mock_incident_prop.py`
    - **Property 26: Mock incident ranking follows Search_Priority with searched rooms last**
    - **Validates: Requirements 21.3, 21.4**
    - Done when: `python -m pytest tools/tests/test_mock_incident_prop.py -q` passes
  - [ ] 3.3 Implement the mock hub entry point
    - Create `tools/mock_hub.py`: reads the floor plan for room→floor mapping, builds `ScriptedIncident`, `create_app`, runs uvicorn on `127.0.0.1:8443` (HTTP for now); `--check` starts, serves one request, and exits 0
    - _Requirements: 21.1, 20.2_
    - Done when: `python tools/mock_hub.py --check` exits 0

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
  - Done when: `python -m pytest hub/tests tools/tests -q; npm --prefix dashboard run test` both pass

- [x] 5. Client core: Store, connection, session, and the pure Scene_Model (P1)
  - [x] 5.1 Implement the in-memory Store
    - Create `dashboard/src/store/store.ts`: pure `reduce`, `lastMessageAt`, `lastKnown` labels, IDLE purge of room and crew entries, discard counter, subscriber list; no storage adapter
    - _Requirements: 7.2, 7.6, 14.4, 17.3_
    - Done when: `npm --prefix dashboard run build` exits 0
  - [x] 5.2 Implement the WebSocket client and backoff
    - Create `dashboard/src/ws/backoff.ts` and `dashboard/src/ws/client.ts`: auth-first message, 4401 → `onAuthFail`, backoff 0.5–5 s, reconnect on `visibilitychange`/`online`, status for "Reconnecting…"
    - _Requirements: 7.3, 7.4, 7.5_
    - Done when: `npm --prefix dashboard run build` exits 0
  - [ ]* 5.3 Write property test for backoff
    - Create `dashboard/tests/backoff.prop.test.ts`
    - **Property 19: Reconnect backoff stays within bounds**
    - **Validates: Requirements 7.4**
    - Done when: `npm --prefix dashboard run test -- backoff.prop` passes
  - [x] 5.4 Implement HTTP wrapper and session startup
    - Create `dashboard/src/api/http.ts` (Bearer header, 401 → pair, 403 → phone mode) and `dashboard/src/auth/session.ts` (try `POST /api/local/token`; else `localStorage["roomsense.token"]`; then `GET /api/whoami`; the only storage key written is `roomsense.token`)
    - _Requirements: 1.5, 2.7, 2.8, 2.9, 17.4_
    - Done when: `npm --prefix dashboard run build` exits 0
  - [x] 5.5 Implement formatting, strings, palette, and patterns
    - Create `dashboard/src/scene/format.ts` (`formatAge`, `parseAge`), `dashboard/src/scene/strings.ts` (all UI copy, `BANNED`), `dashboard/src/scene/palette.ts` (State_Palette with UNKNOWN `#6E6596`, Crew_Palette, text colors, luminance helpers), `dashboard/src/scene/patterns.ts` (pattern and icon ids, SVG pattern defs, canvas pattern painter)
    - _Requirements: 9.2, 9.3, 9.4, 9.6, 10.1, 12.5, 19.3_
    - Done when: `npm --prefix dashboard run build` exits 0
  - [x]* 5.6 Write property test for the palette
    - Create `dashboard/tests/palette.prop.test.ts`
    - **Property 9: The State_Palette is grayscale-distinguishable and never green**
    - **Validates: Requirements 9.2, 9.3, 9.4, 19.3**
    - Done when: `npm --prefix dashboard run test -- palette.prop` passes
  - [x]* 5.7 Write property test for age formatting
    - Create `dashboard/tests/format.prop.test.ts`
    - **Property 15: Age text round-trips**
    - **Validates: Requirements 12.1, 12.5**
    - Done when: `npm --prefix dashboard run test -- format.prop` passes
  - [x] 5.8 Implement the pure Scene_Model
    - Create `dashboard/src/scene/geometry.ts` (centroid, area, edge length) and `dashboard/src/scene/model.ts` (`buildSceneModel` with the step table: IDLE redaction, hub-lost at 5 s, missing-room UNKNOWN, stale, uncalibrated, normal; priority = server ranking filtered to flagged; rank, halo, opacity, saturation, floor-tab counts, all-searched banner, snapshot from `alarm_time_state`, `effectAnchor` = centroid, aria labels; crew items pass through as empty until task 11.4)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 9.1, 9.5, 9.7, 9.8, 9.9, 11.3, 11.5, 11.6, 11.8, 12.1, 12.2, 12.3, 12.4, 12.5, 13.5, 14.2, 16.5, 19.2_
    - Done when: `npm --prefix dashboard run build` exits 0
  - [ ]* 5.9 Write property test for labels and banned words
    - Create `dashboard/tests/scene.labels.prop.test.ts`
    - **Property 2: Only the four labels, no banned words (P-UI1)**
    - **Validates: Requirements 9.1, 9.5, 9.6, 19.2**
    - Done when: `npm --prefix dashboard run test -- scene.labels.prop` passes
  - [ ]* 5.10 Write property test for pass-through and purity
    - Create `dashboard/tests/scene.passthrough.prop.test.ts`
    - **Property 3: The Scene_Model passes server values through and is pure**
    - **Validates: Requirements 8.1, 8.4, 8.5, 8.6, 11.3**
    - Done when: `npm --prefix dashboard run test -- scene.passthrough.prop` passes
  - [ ]* 5.11 Write property test for priority order
    - Create `dashboard/tests/scene.priority.prop.test.ts`
    - **Property 4: Priority list equals the server ranking filtered to flagged rooms (P-UI2)**
    - **Validates: Requirements 8.2, 8.3, 8.5, 11.8**
    - Done when: `npm --prefix dashboard run test -- scene.priority.prop` passes
  - [ ]* 5.12 Write property test for treatment-only encoding
    - Create `dashboard/tests/scene.encoding.prop.test.ts`
    - **Property 5: Encoding depends only on the treatment**
    - **Validates: Requirements 9.2, 9.7, 15.7**
    - Done when: `npm --prefix dashboard run test -- scene.encoding.prop` passes
  - [ ]* 5.13 Write property test for stale and uncalibrated rooms
    - Create `dashboard/tests/scene.stale.prop.test.ts`
    - **Property 7: Stale and uncalibrated rooms get the UNKNOWN treatment (P-UI4)**
    - **Validates: Requirements 12.1, 9.8**
    - Done when: `npm --prefix dashboard run test -- scene.stale.prop` passes
  - [ ]* 5.14 Write property test for hub-lost
    - Create `dashboard/tests/scene.hublost.prop.test.ts`
    - **Property 8: Hub-lost after exactly 5 seconds (P-UI5)**
    - **Validates: Requirements 12.2, 12.3, 12.4, 7.6**
    - Done when: `npm --prefix dashboard run test -- scene.hublost.prop` passes
  - [ ]* 5.15 Write property test for floor tab counts
    - Create `dashboard/tests/scene.floortabs.prop.test.ts`
    - **Property 10: Floor tab counts match the rooms on each floor**
    - **Validates: Requirements 11.5, 15.6**
    - Done when: `npm --prefix dashboard run test -- scene.floortabs.prop` passes
  - [ ]* 5.16 Write property test for the all-searched reminder
    - Create `dashboard/tests/scene.allsearched.prop.test.ts`
    - **Property 11: The all-searched reminder appears exactly when every listed room is searched**
    - **Validates: Requirements 11.6**
    - Done when: `npm --prefix dashboard run test -- scene.allsearched.prop` passes
  - [ ]* 5.17 Write property test for IDLE redaction and Store purge
    - Create `dashboard/tests/scene.idle.prop.test.ts`
    - **Property 12: IDLE shows no occupancy and purges the Store**
    - **Validates: Requirements 14.2, 14.4**
    - Done when: `npm --prefix dashboard run test -- scene.idle.prop` passes
  - [ ]* 5.18 Write property test for the snapshot inset model
    - Create `dashboard/tests/scene.snapshot.prop.test.ts`
    - **Property 14: The snapshot inset shows only `alarm_time_state`**
    - **Validates: Requirements 13.5**
    - Done when: `npm --prefix dashboard run test -- scene.snapshot.prop` passes
  - [ ]* 5.19 Write property test for room-anchored effects
    - Create `dashboard/tests/scene.anchor.prop.test.ts`
    - **Property 18: State effects are anchored to the room, not a point inside it**
    - **Validates: Requirements 16.5**
    - Done when: `npm --prefix dashboard run test -- scene.anchor.prop` passes

- [x] 6. 2D renderer and UI chrome: the laptop safety net (P1)
  - [x] 6.1 Implement the SVG 2D renderer
    - Create `dashboard/src/render2d/svg.tsx`: walls with door gaps, door leaves and swing arcs, furniture blocks, nodes with health dots, link lines (`tx_dead` broken red dash + fault icon; offline RX hides link and shows "!"), room fills with saturation, SVG patterns, SIMULATED overlay text, 35% opacity for searched, greyed state, HTML labels at centroids, MOTION rings and POSSIBLE glow disabled under `prefers-reduced-motion`; no person figures, footprints, heatmaps, trails, smoke, or fire
    - _Requirements: 9.2, 9.9, 11.3, 12.3, 14.3, 16.1, 16.5, 16.6, 16.7_
    - Done when: `npm --prefix dashboard run build` exits 0
  - [x] 6.2 Implement the header and banners
    - Create `dashboard/src/ui/Header.tsx` (Recording_Indicator, Health_Chip, disclaimer, "SIMULATED DATA", "SIMULATED TRIGGER", "2D view" chip, `theme-color` switching), `dashboard/src/ui/HealthChip.tsx` (fault list with cause and action), `dashboard/src/ui/Banners.tsx` (Hub_Lost_Banner, "Reconnecting…", All_Searched_Banner)
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 11.6, 12.2_
    - Done when: `npm --prefix dashboard run build` exits 0
  - [x] 6.3 Implement floor tabs, priority list, and room sheet
    - Create `dashboard/src/ui/FloorTabs.tsx` (1-tap switch, attention and crew counts), `dashboard/src/ui/PriorityList.tsx` (portrait bottom sheet with 3 rows visible, landscape/≥ 900 px side list, rank disc with rank-1 halo, ✓ then confirm = 2 taps, no optimistic reorder), `dashboard/src/ui/RoomSheet.tsx` (state, confidence, motion last seen, `alarm_time_state`, link health, Edge/Hub badge, crew present, mark searched); every control ≥ 56 × 56 px with accessible names
    - _Requirements: 1.2, 1.3, 11.1, 11.2, 11.4, 11.5, 11.7, 11.8, 19.1, 19.2_
    - Done when: `npm --prefix dashboard run build` exits 0
  - [x] 6.4 Implement the floor-plan error screen
    - Create `dashboard/src/ui/FloorplanError.tsx`: plain-language error list with the disclaimer, no plan drawn
    - _Requirements: 6.4, 10.1_
    - Done when: `npm --prefix dashboard run build` exits 0
  - [x] 6.5 Implement laptop controls and wire the app
    - Create `dashboard/src/ui/LaptopControls.tsx` (alarm trigger on IDLE landing, End incident + confirm sheet, "Pair a phone" with code and seconds left, "Revoke phones" + confirm), export `controlsFor(whoami)`; update `dashboard/src/app.tsx` and `dashboard/src/main.tsx` to run session startup, load and validate the floor plan, start the WS client, feed the Store, run `buildSceneModel` on change and on a 1 Hz tick, and render Header, FloorTabs, Renderer_2D, PriorityList, RoomSheet, Banners; safe-area insets and `100dvh`
    - _Requirements: 1.1, 1.4, 1.5, 5.3, 5.4, 5.5, 5.6, 11.7, 14.5_
    - Done when: `npm --prefix dashboard run build` exits 0, then with `python tools/mock_hub.py` running, `Invoke-WebRequest http://127.0.0.1:8443/ -UseBasicParsing` returns status 200
  - [ ]* 6.6 Write unit tests for UI rules
    - Create `dashboard/tests/ui.test.tsx`: `controlsFor` hides laptop controls for phones; no `input`/`textarea` mounted in fire mode; End incident calls the API only after confirm; disclaimer present on Pair and error screens
    - _Requirements: 5.3, 5.5, 10.1, 11.7_
    - Done when: `npm --prefix dashboard run test -- ui.test` passes

- [x] 7. Checkpoint - 2D safety net is demo-able on the laptop
  - Ensure all tests pass, ask the user if questions arise.
  - Done when: `npm --prefix dashboard run build; npm --prefix dashboard run test; python -m pytest hub/tests tools/tests -q` pass, and with `python tools/mock_hub.py` running, `http://127.0.0.1:8443` in a laptop browser shows the floor plan, the alarm button starts the scripted incident, and R1 is rank 1

- [ ] 8. Phone pairing, HTTPS listeners, and the PWA shell (P2)
  - [x] 8.1 Implement listener planning and HTTPS serving
    - Create `hub/web/listeners.py` (`plan_listeners` pure, `serve` running one uvicorn server per listener with TLS from `HUB_CERT_FILE`/`HUB_KEY_FILE`, plain HTTP on 127.0.0.1 only when the cert is missing, skip and log missing bind addresses, never `0.0.0.0`); update `tools/mock_hub.py` to use it
    - _Requirements: 4.1, 4.2, 4.3, 4.4_
    - Done when: `python tools/mock_hub.py --check` exits 0 and, with no cert present, its log names the missing cert file
  - [ ]* 8.2 Write unit tests for listener planning
    - Create `hub/tests/test_listeners.py`: cert present/missing, bind address missing, no `0.0.0.0`
    - _Requirements: 4.1, 4.2, 4.3, 4.4_
    - Done when: `python -m pytest hub/tests/test_listeners.py -q` passes
  - [x] 8.3 Implement the in-app pairing screen
    - Create `dashboard/src/ui/Pair.tsx` (6-digit on-screen keypad with 56 px keys, 401 and 429 messages, disclaimer); update `dashboard/src/app.tsx` to show it on missing or rejected token and to drop the stored token on WS close 4401
    - _Requirements: 2.8, 2.9, 10.1, 19.1_
    - Done when: `npm --prefix dashboard run build` exits 0
  - [x] 8.4 Configure the PWA shell, manifest, icons, and fonts
    - Update `dashboard/vite.config.ts` with VitePWA per the design (`runtimeCaching: []`, `navigateFallbackDenylist` for `/api/` and `/ws`); create team-drawn icons in `dashboard/public/icons/` (192, 512, maskable 512, `apple-touch-icon.png`) with no third-party marks; add `dashboard/public/fonts/` with Atkinson Hyperlegible woff2 and `OFL.txt`, or if the files cannot be obtained offline, use the system font stack and create `dashboard/public/fonts/TODO.md` naming the missing files (never a CDN link); update `dashboard/index.html` with `apple-touch-icon` and `theme-color`
    - _Requirements: 17.1, 17.2, 18.1, 18.2, 18.3, 18.4, 18.5_
    - Done when: `npm --prefix dashboard run build` exits 0 and `Test-Path hub/static/sw.js` and `Test-Path hub/static/manifest.webmanifest` are True
  - [ ]* 8.5 Write privacy and bundle tests on the build output
    - Create `dashboard/tests/privacy/dist.test.ts`: `hub/static/sw.js` has no runtime routes beyond precache and navigation fallback; no MAC-like string in `hub/static/**` or `hub/config/floorplan.json`; no absolute external URL in `hub/static/**` except the SVG namespace; gzipped JS total ≤ 350 KB
    - _Requirements: 6.7, 17.1, 17.2, 17.5, 18.1, 22.1_
    - Done when: `npm --prefix dashboard run build; npm --prefix dashboard run test -- privacy` passes
  - [ ]* 8.6 Write property test for browser storage writes
    - Create `dashboard/tests/storage.prop.test.ts` (instrumented `localStorage`, `sessionStorage`, `fake-indexeddb`, and a fake `caches`)
    - **Property 13: Only the token key is ever written to browser storage**
    - **Validates: Requirements 17.3, 17.4**
    - Done when: `npm --prefix dashboard run test -- storage.prop` passes

- [x] 9. Checkpoint - Phone pairing and PWA install
  - Ensure all tests pass, ask the user if questions arise.
  - Done when: all test commands from task 7 pass, `python tools/check_pins.py` exits 0, and with the mkcert cert in `hub/certs/`, `python tools/mock_hub.py` logs listeners on `127.0.0.1:8443` and `192.168.137.1:8443` with TLS

- [ ] 10. Renderer choice and the 3D renderer (P3, cut 4)
  - [ ] 10.1 Implement the renderer chooser
    - Create `dashboard/src/render3d/choose.ts` (`chooseRenderer` pure) and wire it in `dashboard/src/app.tsx` with `include3d` from a build flag (default false until 10.3 lands), so the 2D renderer is always the fallback
    - _Requirements: 16.4_
    - Done when: `npm --prefix dashboard run build` exits 0
  - [ ]* 10.2 Write property test for the renderer chooser
    - Create `dashboard/tests/choose.prop.test.ts`
    - **Property 17: Renderer choice falls back to 2D exactly when required**
    - **Validates: Requirements 16.4**
    - Done when: `npm --prefix dashboard run test -- choose.prop` passes
  - [ ]* 10.3 Implement the 3D scene geometry (cut 4)
    - Create `dashboard/src/render3d/scene.ts`, `walls.ts` (merged per-floor geometry, 1.0 m cutaway, door openings, top cap, baked contact-shadow strips), `floors.ts` (pattern `CanvasTexture`, saturation, opacity, SIMULATED overlay), `nodes.ts` (devices at height `h`, status LED), `links.ts` (dashed tube beams with speed ∝ `measured_pps`, `tx_dead` and offline styles); lighting = HemisphereLight + DirectionalLight with 1024² shadow map; no person figures, footprints, heatmaps, trails, smoke, or fire
    - _Requirements: 16.2, 16.5, 16.6, 16.7_
    - Done when: `npm --prefix dashboard run build` exits 0
  - [ ]* 10.4 Implement 3D labels and camera (cut 4)
    - Create `dashboard/src/render3d/labels.ts` (CSS2DRenderer label, confidence, rank badge with halo, chips at centroids, accessible names) and `dashboard/src/render3d/camera.ts` (orthographic isometric 35°/45°, 90° rotate snaps, clamped pinch zoom, double-tap to frame, `frameRooms(ids, 600ms)`)
    - _Requirements: 16.3, 13.3, 19.2_
    - Done when: `npm --prefix dashboard run build` exits 0
  - [ ]* 10.5 Wire the 3D renderer with performance budget and fallback (cut 4)
    - Update `dashboard/src/app.tsx` to enable `include3d`, feed frame times and context-loss events to `chooseRenderer`, cap pixel ratio at 2, render on demand, pause on `document.hidden`, create the context with `failIfMajorPerformanceCaveat: true`
    - _Requirements: 16.4, 22.2, 22.3_
    - Done when: `npm --prefix dashboard run build` exits 0 and `npm --prefix dashboard run test -- privacy` still reports gzipped JS ≤ 350 KB

- [ ] 11. Fire-mode polish, crew markers, and floor-2 rooms (P4)
  - [-] 11.1 Implement the fire-mode entry sequence
    - Create `dashboard/src/ui/FireEntry.tsx` (red header within one frame, 1 s red flash unless reduced motion, frame Flagged_Rooms within 600 ms via the active renderer, open Priority_List to 3 rows); update `dashboard/src/app.tsx` to mount it on the IDLE → ALARM_ACTIVE transition
    - _Requirements: 13.1, 13.2, 13.3_
    - Done when: `npm --prefix dashboard run build` exits 0
  - [-] 11.2 Implement best-effort Screen Wake Lock
    - Create `dashboard/src/ui/wakelock.ts`: request on fire entry, re-request on visible, swallow unsupported or rejected requests
    - _Requirements: 13.4_
    - Done when: `npm --prefix dashboard run build` exits 0
  - [-] 11.3 Implement the snapshot inset (cut 3: toggle variant)
    - Create `dashboard/src/ui/SnapshotInset.tsx`: 2D mini-plan from `scene.snapshot` labeled "AT ALARM", tap to swap with the live view; a `snapshotMode: "inset" | "toggle"` constant selects the cut-3 "At alarm" toggle variant
    - _Requirements: 13.5, 13.6_
    - Done when: `npm --prefix dashboard run build` exits 0
  - [ ]* 11.4 Implement crew markers and chips (cut 1)
    - Update `dashboard/src/scene/model.ts` with the crew rule table (solid marker only for room + medium/high; chips for near, between, low, lost; hollow last-heard marker; Crew_Palette only) and `dashboard/src/render2d/svg.tsx` to draw the chevron pin at `crewSlot` and chips on the shared wall or door; show annotation text on labels only
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7_
    - Done when: `npm --prefix dashboard run build` exits 0
  - [ ]* 11.5 Write property test for crew markers (cut 1)
    - Create `dashboard/tests/scene.crew.prop.test.ts`
    - **Property 6: Crew markers never use state colors or false precision (P-UI3)**
    - **Validates: Requirements 15.1, 15.2, 15.3, 15.4, 15.5**
    - Done when: `npm --prefix dashboard run test -- scene.crew.prop` passes
  - [ ]* 11.6 Add floor-2 simulated rooms (cut 2)
    - Update `hub/config/floorplan.json` with F2 holding R3 Office, R4 Classroom, R5 Break room, each `simulated: true`, with walls, doors, and furniture; the mock picks them up from the floor plan
    - _Requirements: 6.6, 9.9_
    - Done when: `npm --prefix dashboard run test -- floorplan.committed` passes and the JSON lists 3 rooms on F2
  - [ ]* 11.7 Write unit tests for fire entry and wake lock
    - Create `dashboard/tests/fireentry.test.tsx`: flash shown without reduced motion and skipped with it; wake lock absent or rejecting does not throw; re-request on visibility
    - _Requirements: 13.2, 13.4_
    - Done when: `npm --prefix dashboard run test -- fireentry` passes

- [ ] 12. End-to-end tests on phone and laptop emulation (P5)
  - [ ]* 12.1 Set up Playwright with the mock hub
    - Create `dashboard/playwright.config.ts` (projects "iPhone 14", "Pixel 7", "Desktop Chrome"; `webServer` runs `python ../tools/mock_hub.py` with `HUB_BIND_HOSTS=127.0.0.1` and `HUB_TEST_FORCE_REMOTE=1`) and `dashboard/tests/e2e/fixtures.ts` (phone projects send `X-Test-Remote: 1` and pair through the UI using a code fetched by the laptop fixture)
    - _Requirements: 5.3, 19.1_
    - Done when: `npx --prefix dashboard playwright install chromium webkit; npm --prefix dashboard run e2e -- --list` lists the three projects
  - [ ]* 12.2 Write grayscale distinguishability test
    - Create `dashboard/tests/e2e/grayscale.spec.ts`: one room per treatment, grayscale screenshot, pairwise mean pixel difference over room regions > 12/255
    - _Requirements: 9.3_
    - Done when: `npm --prefix dashboard run e2e -- grayscale` passes
  - [ ]* 12.3 Write touch target and tap-count tests
    - Create `dashboard/tests/e2e/targets.spec.ts`: every visible interactive element ≥ 56 × 56; mark searched in 2 clicks; floor switch in 1 click
    - _Requirements: 11.2, 11.5, 19.1_
    - Done when: `npm --prefix dashboard run e2e -- targets` passes
  - [ ]* 12.4 Write phone-controls test
    - Create `dashboard/tests/e2e/phone-controls.spec.ts`: phone projects render no alarm, End incident, pairing-code, or Revoke control; direct API calls from the phone context return 403
    - _Requirements: 5.1, 5.3_
    - Done when: `npm --prefix dashboard run e2e -- phone-controls` passes
  - [ ]* 12.5 Write fire-entry timing and reduced-motion test
    - Create `dashboard/tests/e2e/fire-entry.spec.ts`: red header within 300 ms of the ALARM_ACTIVE message; no flash with `reducedMotion: "reduce"`; rank-1 badge with halo visible within 5 s
    - _Requirements: 13.1, 13.2, 13.3_
    - Done when: `npm --prefix dashboard run e2e -- fire-entry` passes
  - [ ]* 12.6 Write hub-lost and offline-start test
    - Create `dashboard/tests/e2e/hub-lost.spec.ts`: stop the mock hub, banner within 6 s and every room greyed with "STALE — last known"; offline reload shows shell, disclaimer, and banner
    - _Requirements: 12.2, 12.3, 18.5_
    - Done when: `npm --prefix dashboard run e2e -- hub-lost` passes
  - [ ]* 12.7 Write on-device storage test after a full incident
    - Create `dashboard/tests/e2e/storage.spec.ts`: run trigger → marks → End incident; Cache Storage holds only the Workbox precache, IndexedDB has no non-Workbox databases, `localStorage` keys ⊆ {`roomsense.token`}
    - _Requirements: 17.3, 17.4_
    - Done when: `npm --prefix dashboard run e2e -- storage` passes

- [ ] 13. Kiro artifacts, documentation, and committed build (P5)
  - [ ] 13.1 Write the UI steering file
    - Create `.kiro/steering/ui.md` (inclusion: fileMatch on `dashboard/**`): State_Palette with the UNKNOWN deviation note, the state encoding table, Crew_Palette, Banned_Words regex, "Search priority" and "Motion last seen" wording, no person figures, footprints, heatmaps, trails, smoke, or fire, the 56 px rule, and "client never re-ranks"
    - _Requirements: 23.4_
    - Done when: `Select-String -Path .kiro/steering/ui.md -Pattern '56'` and `-Pattern '#6E6596'` both return matches
  - [ ] 13.2 Author agent hooks
    - Create `.kiro/hooks/dashboard-props-on-save.json` (PostFileSave matcher `dashboard[\\/]src[\\/].*` → `npm --prefix dashboard run test`), `.kiro/hooks/ui-banned-words.json` (PostFileSave on `dashboard[\\/]src[\\/].*` → a script `tools/scan_ui.py` that fails on Banned_Words in `scene/strings.ts` and MAC-like strings in `dashboard/src` and `hub/config`), `.kiro/hooks/sw-no-runtime-cache.json` (PostFileSave on `vite.config.ts` → `npm --prefix dashboard run build; npm --prefix dashboard run test -- privacy`); create `tools/scan_ui.py`
    - _Requirements: 9.6, 6.7, 17.1_
    - Done when: `python tools/scan_ui.py` exits 0 and `Get-ChildItem .kiro/hooks/*.json | ForEach-Object { Get-Content $_ -Raw | ConvertFrom-Json }` parses all three files
  - [ ] 13.3 Write the README section
    - Update `README.md` (create if missing) with: prerequisites; `npm --prefix dashboard ci` and build; `python -m pip install -r hub/requirements.txt`; `python tools/mock_hub.py`; mkcert steps from plan section 5 (install, issue cert for `192.168.137.1 localhost 127.0.0.1` into `hub/certs/`, AirDrop `rootCA.pem`, install profile, enable full trust, verify in Safari, reissue if the hotspot IP differs); Windows hotspot on 5 GHz; Add to Home Screen; pairing inside the installed app; Revoke phones; Auto-Lock to Never for iOS < 18.4; the residual security risks from the design; how to run all tests
    - _Requirements: 23.3_
    - Done when: `Select-String -Path README.md -Pattern 'mkcert'` and `-Pattern 'Revoke phones'` both return matches
  - [ ] 13.4 Update CONTEXT.md
    - Record D1–D5, pairing, floor-plan JSON, laptop-only End incident and alarm trigger, committed `hub/static`, the UNKNOWN color deviation; move the PWA item out of "Still open"; add Kiro usage log rows for this spec, the steering file, the hooks, and the fast-check/Hypothesis properties
    - _Requirements: 23.5_
    - Done when: `Select-String -Path CONTEXT.md -Pattern 'D5'` returns a match
  - [ ] 13.5 Build and commit the static output
    - Run the production build into `hub/static` and stage it with the source changes so judges can run `python tools/mock_hub.py` without Node
    - _Requirements: 23.2_
    - Done when: `npm --prefix dashboard run build; git status --porcelain hub/static` lists the built files and `python tools/mock_hub.py --check` exits 0

- [ ] 14. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
  - Done when: `python tools/check_pins.py; python tools/scan_ui.py; python -m pytest hub/tests tools/tests -q; npm --prefix dashboard run test; npm --prefix dashboard run e2e` all pass

## Notes

- Tasks marked with `*` are optional: test sub-tasks, plus the cuttable features (cut 1 crew chips 11.4–11.5, cut 2 floor-2 rooms 11.6, cut 4 3D renderer 10.3–10.5). Cut 3 is handled inside required task 11.3 by the toggle variant.
- Never cut: disclaimer, Recording_Indicator, Health_Chip, hub-lost banner, stale display (tasks 5.8, 6.2, 6.1).
- The hub web layer is built with token and loopback guards from the start (task 2), so no unauthenticated data route ever exists, even before the phone work in task 8.
- Property tests use ≥ 100 runs and carry the tag `Feature: pwa-dashboard, Property <n>: <title>`.
- Each task references requirements in this spec; parent requirements are cited as "parent R…" in requirements.md.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["1.4", "1.6", "2.1"] },
    { "id": 2, "tasks": ["1.5", "1.7", "1.8", "2.2", "2.3", "2.4", "2.5", "5.1", "5.5"] },
    { "id": 3, "tasks": ["2.6", "2.7", "5.2", "5.6", "5.7", "5.8"] },
    { "id": 4, "tasks": ["2.8", "2.9", "2.10", "3.1", "5.3", "5.4", "5.9", "5.10", "5.11", "5.12", "5.13", "5.14", "5.15", "5.16", "5.17", "5.18", "5.19"] },
    { "id": 5, "tasks": ["3.2", "3.3", "6.1", "6.2", "6.3", "6.4"] },
    { "id": 6, "tasks": ["6.5", "8.1"] },
    { "id": 7, "tasks": ["6.6", "8.2", "8.3"] },
    { "id": 8, "tasks": ["8.4", "8.6", "10.1", "11.2", "11.3"] },
    { "id": 9, "tasks": ["8.5", "10.2"] },
    { "id": 10, "tasks": ["10.3", "11.1", "11.6"] },
    { "id": 11, "tasks": ["10.4", "11.4"] },
    { "id": 12, "tasks": ["10.5", "11.5", "11.7", "12.1"] },
    { "id": 13, "tasks": ["12.2", "12.3", "12.4", "12.5", "12.6", "12.7", "13.1", "13.2"] },
    { "id": 14, "tasks": ["13.3", "13.4"] },
    { "id": 15, "tasks": ["13.5"] }
  ]
}
```
