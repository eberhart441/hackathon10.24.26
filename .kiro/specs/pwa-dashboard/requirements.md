# Requirements Document

## Introduction

This feature adds a phone-installable progressive web app (PWA) dashboard for Beacon, plus the minimal hub web layer and mock hub it needs. A responder opens the app on an iPhone and, within 5 seconds of fire mode, sees a realistic floor plan of the building, the room to search first, and how much to trust each room. "Realistic" applies to the architecture only. Occupancy data stays honest: room level only, four states only, and never "empty".

This spec extends the parent spec at `.kiro/specs/beacon-occupancy-tool/`. Parent requirements are referenced as "parent R<n>.<m>" (for example parent R13.4) and are not copied. Terms defined in the parent glossary (Room_State, Fire_Mode, Recording_Indicator, Health_Chip, Simulated_Data_Badge, Crew_Marker, Tag_Location, Searched_Mark, Search_Priority, Confidence, Last_Seen, IDLE_State, ALARM_ACTIVE_State, Incident_Record, Hub) keep their parent meaning. The WebSocket message shapes (`room_states`, `health`, `crew`, `recording`) and the REST paths are the ones in the parent design's "Hub: Web Server" section. The source plan is `.scratch/pwa-dashboard/plan.md`.

The repository contains only docs and specs today, so this spec also delivers a reusable FastAPI web layer (`hub/`) with a pluggable state source, and a scripted mock incident (`tools/mock_hub.py`) so the dashboard can be built and demonstrated before the sensing pipeline exists.

### Resolved decisions

These decisions amend the parent spec for this feature only.

- **D1 Display device.** The phone PWA is the responder view. The laptop runs the same app in a browser as the installer and presenter view. The layout is phone-first (portrait), with a landscape and laptop layout that shows the priority list as a side list (parent R13.2). This supersedes parent Introduction decision 2 and parent R10.2 for the dashboard display device.
- **D2 Network exposure.** The hub also listens on the Windows Mobile Hotspot interface (5 GHz, WPA2, usually `192.168.137.1`). Every HTTP API route and the WebSocket require a pairing token. The phone can only mark rooms searched. End incident and the alarm trigger are laptop-only: the phone never shows them, and the hub rejects them from non-loopback clients. This supersedes the parent design's Security note ("binds to localhost only", "responder endpoints unauthenticated"). Where plan section 0 row D2 lists End incident as a phone action, that row is outdated; plan section 5 governs.
- **D3 Secure context.** The demo phone is an iPhone. The hub serves HTTPS with an mkcert certificate whose subject alternative names are `192.168.137.1`, `localhost`, and `127.0.0.1`. The mkcert root CA is installed and fully trusted on the iPhone before the event.
- **D4 Rooms.** Floor F1 holds R1 (the measured conference room, 3.96 m × 2.84 m, live) and R2 (live if the second link works). Floor F2 holds 2 to 4 rooms flagged simulated and labeled SIMULATED (parent R10.5).
- **D5 Realism scope.** Realistic architecture only: walls, door gaps and swing arcs, furniture blocks, nodes, link beams, and lighting. No person figures, footprints, heatmaps, in-room trails, smoke, or fire particles.
- **Pairing.** Pairing happens inside the installed app, because an iOS home-screen PWA has storage separate from Safari. The laptop shows a 6-digit, single-use code valid for 2 minutes, served only to loopback clients. The phone sends `POST /api/pair {code}`; the hub allows 5 attempts per minute per client and returns a long random token. The app stores the token in `localStorage` (the token is not occupancy data). The hub persists tokens in git-ignored `hub/config/secrets.json`, so a hub restart does not unpair the phone. The laptop has a "Revoke phones" control. The WebSocket's first client message is `{"type":"auth","token":...}`; HTTP uses `Authorization: Bearer <token>`.
- **Floor plan.** The team hand-edits `hub/config/floorplan.json` (meters). The hub serves it at `GET /api/floorplan` (token required). The app validates it on load and shows plain-language errors. There is no floor-plan editor.
- **Alerts.** No haptics (iOS has no `navigator.vibrate`). Fire-mode entry uses a 1-second full-screen red flash, skipped under `prefers-reduced-motion`. Screen Wake Lock is best effort (iOS 18.4 or later in an installed PWA).
- **Build output.** The built `hub/static` directory is committed so judges can run the hub without Node.
- **Cut order** (plan section 6): crew-marker chips first, then floor-2 simulated rooms, then the snapshot inset becomes a toggle, then the 3D renderer (keep 2D). The disclaimer, Recording_Indicator, Health_Chip, hub-lost banner, and stale display are never cut.

## Glossary

- **PWA**: The installable dashboard web app in `dashboard/`, built with Vite, TypeScript, and Preact, and served by the Hub_Web_Layer.
- **Hub_Web_Layer**: The FastAPI application in `hub/` that serves the App_Shell, the REST API, and the WebSocket, and enforces token and loopback rules.
- **State_Source**: The pluggable interface through which the Hub_Web_Layer obtains room states, health, crew, and recording data and forwards alarm, end-incident, and mark-searched commands. The real pipeline and the Mock_Hub each provide one.
- **Mock_Hub**: `tools/mock_hub.py`, which runs the Hub_Web_Layer with a scripted incident State_Source that sets `simulated: true`.
- **Loopback_Client**: An HTTP or WebSocket client whose remote address is `127.0.0.1` or `::1`.
- **Laptop_Client**: The PWA running in a browser on the hub laptop as a Loopback_Client.
- **Phone_Client**: The PWA running on a device that is not a Loopback_Client, for example the iPhone on the hotspot.
- **Laptop_Only_Endpoint**: Any of the alarm-trigger, end-incident, pairing-code, revoke-phones, and local-token endpoints.
- **Pairing_Code**: A 6-digit, single-use code, valid for 120 seconds, that a Phone_Client exchanges for a Pairing_Token.
- **Pairing_Token**: A random bearer token of at least 32 random bytes issued by the Hub_Web_Layer, required on every protected route and on the WebSocket.
- **Protected_Route**: Every `/api/*` HTTP route and the `/ws` WebSocket, except `POST /api/pair` and `POST /api/local/token`.
- **App_Shell**: The static HTML, JavaScript, CSS, fonts, icons, and manifest that make up the PWA, with no occupancy data.
- **Service_Worker**: The PWA service worker generated by vite-plugin-pwa, which precaches the App_Shell only.
- **Floorplan_File**: `hub/config/floorplan.json`, the hand-edited description of floors, rooms, doors, furniture, nodes, and links in meters.
- **Floorplan_Validator**: The PWA function that checks a Floorplan_File and returns either a valid floor plan or a list of plain-language errors.
- **WS_Client**: The PWA module that opens the WebSocket, authenticates, parses typed messages, and reconnects.
- **Store**: The PWA in-memory state holding the latest `room_states`, `health`, `crew`, and `recording` messages, the link status, and `lastMessageAt`.
- **Scene_Model**: The pure PWA function `buildSceneModel(floorplan, store, now)` that returns one Room_Descriptor per room plus banners and counts.
- **Room_Descriptor**: The per-room drawing instruction produced by the Scene_Model (state label, icon, pattern, fill, rank, confidence text, stale text, searched flag, simulated flag, crew items, annotations).
- **Renderer_2D**: The SVG top-down renderer that draws Room_Descriptors.
- **Renderer_3D**: The three.js orthographic isometric renderer that draws Room_Descriptors, with HTML labels pinned by CSS2DRenderer.
- **Priority_List**: The list of Flagged_Rooms in server ranking order, shown as a bottom sheet in portrait and a side list in landscape.
- **Room_Sheet**: The bottom sheet that shows one room's details.
- **Floor_Tabs**: The control that switches the visible floor and shows per-floor attention and crew counts.
- **Flagged_Room**: A room whose Room_State is MOTION, POSSIBLE, or UNKNOWN.
- **Hub_Lost_Banner**: The full-width banner shown when no hub message has arrived for 5 seconds (parent R19.8).
- **All_Searched_Banner**: The banner "No detection rooms still require a sweep" (parent R13.7).
- **Snapshot_Inset**: The small 2D view of each room's `alarm_time_state` shown beside the live view (parent R14.1).
- **State_Palette**: The four Room_State fill colors: MOTION `#FF4D2E`, POSSIBLE `#FFB020`, UNKNOWN `#6E6596`, NO DETECTION `#3A4250`.
- **Crew_Palette**: The two Crew_Marker colors `#FFFFFF` and `#111111`.
- **Banned_Word**: Any user-visible word matching the case-insensitive pattern `\b(empty|clear(ed)?|safe)\b`.
- **Age_Text**: Elapsed time formatted as `m:ss` (or `h:mm:ss` from 1 hour), for example "0:42 ago".

## Requirements

### Requirement 1: Phone-First Responder View and Laptop Presenter View

**User Story:** As a responder, I want the dashboard on my phone with the same content the presenter sees on the laptop, so that I can act on it while moving through the building.

#### Acceptance Criteria

1. THE PWA SHALL serve one App_Shell to both the Phone_Client and the Laptop_Client.
2. WHILE the viewport is in portrait orientation, THE PWA SHALL show the header, the floor plan at about 55 percent of the viewport height, and the Priority_List as a bottom sheet.
3. WHILE the viewport is in landscape orientation or wider than 900 CSS pixels, THE PWA SHALL show the Priority_List as a side list to the right of the floor plan (parent R13.2).
4. THE PWA SHALL lay out content inside `env(safe-area-inset-*)` and size the root container with `100dvh`.
5. WHEN the PWA starts, THE PWA SHALL request `GET /api/whoami` and show Laptop_Only_Endpoint controls only WHEN the response reports a Loopback_Client.

### Requirement 2: Pairing and Tokens

**User Story:** As the installer, I want the phone paired once with a short code, so that only our paired devices can read incident data.

#### Acceptance Criteria

1. WHEN a Laptop_Client requests `GET /api/local/pairing-code`, THE Hub_Web_Layer SHALL return a new 6-digit Pairing_Code valid for 120 seconds and invalidate any earlier unused Pairing_Code.
2. WHEN a client sends `POST /api/pair` with the current unexpired, unused Pairing_Code, THE Hub_Web_Layer SHALL return a new Pairing_Token and mark that Pairing_Code used.
3. IF a client sends `POST /api/pair` with a Pairing_Code that is wrong, expired, or already used, THEN THE Hub_Web_Layer SHALL return HTTP 401 and issue no Pairing_Token.
4. IF a client address sends more than 5 `POST /api/pair` requests within any 60-second window, THEN THE Hub_Web_Layer SHALL return HTTP 429 for each additional request in that window and evaluate no code for that request.
5. WHEN the Hub_Web_Layer issues a phone Pairing_Token, THE Hub_Web_Layer SHALL persist the SHA-256 hash of that Pairing_Token in `hub/config/secrets.json` and SHALL accept that Pairing_Token after a hub restart.
6. WHEN a Laptop_Client requests `POST /api/local/revoke-phones`, THE Hub_Web_Layer SHALL delete every persisted phone Pairing_Token hash and close every open WebSocket authenticated with a phone Pairing_Token.
7. WHEN a Laptop_Client requests `POST /api/local/token`, THE Hub_Web_Layer SHALL return a Pairing_Token that is held in memory only and is valid until the hub process stops.
8. WHEN a Phone_Client has no stored Pairing_Token or receives HTTP 401, THE PWA SHALL show the pairing screen with a numeric code input of 6 digits.
9. WHEN pairing succeeds, THE PWA SHALL store the Pairing_Token in `localStorage` under the key `beacon.token` and load the floor plan.

### Requirement 3: Token Enforcement on Every Route

**User Story:** As the team, I want every data route locked behind a token, so that other devices on the hotspot cannot read room states.

#### Acceptance Criteria

1. IF a request to a Protected_Route carries no `Authorization: Bearer` header or a Pairing_Token the Hub_Web_Layer did not issue, THEN THE Hub_Web_Layer SHALL return HTTP 401 (or HTTP 403 when Requirement 5.1 applies) and SHALL return no room, crew, health, recording, or floor-plan data.
2. WHEN a client opens `/ws`, THE Hub_Web_Layer SHALL send no message until the client's first message is `{"type":"auth","token":<valid Pairing_Token>}`.
3. IF the first WebSocket message is not a valid auth message or does not arrive within 5 seconds, THEN THE Hub_Web_Layer SHALL close the WebSocket with close code 4401.
4. THE Hub_Web_Layer SHALL compare Pairing_Tokens by constant-time comparison of SHA-256 hashes.
5. THE Hub_Web_Layer SHALL serve the App_Shell, `POST /api/pair`, and `POST /api/local/token` without a Pairing_Token.

### Requirement 4: Network Listeners and HTTPS

**User Story:** As the team, I want the hub reachable from the phone over HTTPS on the hotspot only, so that the PWA can install and nothing is exposed to the venue network.

#### Acceptance Criteria

1. THE Hub_Web_Layer SHALL listen only on the addresses listed in the `HUB_BIND_HOSTS` setting, with a default of `127.0.0.1,192.168.137.1`, on the port in `HUB_PORT` with a default of 8443.
2. WHERE `HUB_CERT_FILE` and `HUB_KEY_FILE` name readable files, THE Hub_Web_Layer SHALL serve HTTPS and WSS on every listener using that certificate and key.
3. IF the certificate or key file is missing, THEN THE Hub_Web_Layer SHALL serve plain HTTP on `127.0.0.1` only, skip every non-loopback listener, and log a plain-language message naming the missing file.
4. IF a configured bind address is not present on the laptop, THEN THE Hub_Web_Layer SHALL log a plain-language message naming that address and continue serving on the remaining listeners.
5. THE repository SHALL commit `hub/.env.example` and SHALL list `hub/.env`, `hub/certs/`, `*.pem`, and `hub/config/secrets.json` in `.gitignore`.

### Requirement 5: Laptop-Only Controls

**User Story:** As the presenter, I want the alarm trigger and End incident only on the laptop, so that an accidental phone tap cannot start or wipe an incident in front of the judges.

#### Acceptance Criteria

1. IF a client that is not a Loopback_Client calls a Laptop_Only_Endpoint, THEN THE Hub_Web_Layer SHALL return HTTP 403 and leave the system state unchanged, regardless of the Pairing_Token presented.
2. IF a WebSocket client that is not a Loopback_Client sends `trigger_alarm` or `end_incident`, THEN THE Hub_Web_Layer SHALL ignore that message and leave the system state unchanged.
3. WHILE the PWA runs as a Phone_Client, THE PWA SHALL render no alarm-trigger, End incident, pairing-code, or Revoke phones control.
4. WHILE the PWA runs as a Laptop_Client in IDLE_State, THE PWA SHALL show the alarm-trigger button on the landing view (parent R16.1) and the "SIMULATED TRIGGER" label after the button is used (parent R16.3).
5. WHEN the Laptop_Client user taps End incident, THE PWA SHALL show a confirm sheet and SHALL call `POST /api/incident/end` only after the confirm tap (parent R15.11).
6. WHILE the PWA runs as a Laptop_Client, THE PWA SHALL show a "Pair a phone" control that displays the current Pairing_Code with its remaining validity in seconds, and a "Revoke phones" control with a confirm tap.
7. WHEN any client with a valid Pairing_Token calls `POST /api/rooms/{room_id}/searched`, THE Hub_Web_Layer SHALL forward the Searched_Mark to the State_Source and broadcast the next `room_states` message within 1 second.

### Requirement 6: Floor Plan File and Validation

**User Story:** As the team, I want to describe the building in a hand-edited JSON file that the app checks, so that we can adjust the layout at the venue without a rebuild and never draw a broken plan.

#### Acceptance Criteria

1. WHEN a client with a valid Pairing_Token requests `GET /api/floorplan`, THE Hub_Web_Layer SHALL return the current contents of the Floorplan_File read at request time.
2. THE Floorplan_File SHALL describe floors, rooms (id, name, polygon, doors, furniture, crew slot, simulated flag), nodes (id, role, room, position, height), and links (TX node id, RX node id), with all lengths in meters.
3. WHEN the PWA loads a floor plan, THE Floorplan_Validator SHALL check that every room polygon has at least 3 vertices and non-zero area, every door's offset plus width fits within its wall edge, every node's room id exists, every link references an existing TX node and an existing RX node, and every floor, room, and node id is unique.
4. IF the Floorplan_Validator finds one or more errors, THEN THE PWA SHALL show a plain-language error list naming each rule and the offending id, and SHALL draw no floor plan.
5. THE repository SHALL provide a Floorplan_File with floor F1 containing R1 at 3.96 m × 2.84 m with a 0.91 m door at a corner of a 2.84 m wall, and R2.
6. WHERE floor-2 simulated rooms are included (cut order item 2), THE Floorplan_File SHALL contain floor F2 with 2 to 4 rooms whose simulated flag is true.
7. IF the Floorplan_File or any served payload contains a string matching `([0-9a-f]{2}:){5}[0-9a-f]{2}` (case-insensitive), THEN the privacy test suite SHALL fail.

### Requirement 7: Typed Messages and Connection

**User Story:** As a developer, I want the PWA's message types to match the hub exactly and the socket to recover on its own, so that the phone shows current data after it wakes up.

#### Acceptance Criteria

1. THE WS_Client SHALL parse `room_states`, `health`, `crew`, and `recording` messages using the field names and value sets in the parent design's "Hub: Web Server" section.
2. IF a received message fails parsing, THEN THE WS_Client SHALL discard that message, leave the Store unchanged, and count the discard.
3. WHEN the WebSocket opens, THE WS_Client SHALL send `{"type":"auth","token":<Pairing_Token>}` as its first message.
4. WHEN the WebSocket closes, THE WS_Client SHALL reconnect with exponential backoff starting at 0.5 seconds and capped at 5 seconds.
5. WHEN the document becomes visible or the browser fires `online`, THE WS_Client SHALL reconnect immediately and show "Reconnecting…" until the first message arrives.
6. WHEN any valid message arrives, THE Store SHALL set `lastMessageAt` to the receipt time.
7. THE Hub_Web_Layer SHALL broadcast a `health` message at least once per second in every system state.

### Requirement 8: Server Is the Source of Truth

**User Story:** As a responder, I want the phone to show exactly what the hub decided, so that the safety logic lives in one tested place.

#### Acceptance Criteria

1. THE Scene_Model SHALL take each room's Room_State, Confidence, stale flag, searched flag, and annotation from the latest `room_states` message without recomputing them.
2. THE Priority_List SHALL list Flagged_Rooms in the order of the server `ranking` array and SHALL apply no other ordering (parent R9).
3. THE Scene_Model SHALL assign each listed room a rank badge equal to its 1-based position in the Priority_List.
4. IF a room on the floor plan is absent from an ALARM_ACTIVE `room_states` message, THEN THE Scene_Model SHALL give that room the UNKNOWN treatment with the text "No data from hub".
5. IF a room in a `room_states` message is absent from the floor plan, THEN THE Priority_List SHALL still list that room in server order with the note "Not on floor plan".
6. THE Scene_Model SHALL be a pure function of the floor plan, the Store contents, and the current time.

### Requirement 9: Four-State Encoding

**User Story:** As a responder, I want each state readable by label, icon, and pattern as well as color, so that I can tell states apart in glare, in grayscale, or with color-vision deficiency.

#### Acceptance Criteria

1. THE PWA SHALL label every Room_State with exactly one of MOTION, POSSIBLE, UNKNOWN, and NO DETECTION (parent R8.2, R12.1).
2. THE PWA SHALL render every Room_State with its State_Palette fill, a state-specific icon, the state label, and a state-specific floor pattern: solid for MOTION, 45-degree hatch for POSSIBLE, cross-hatch for UNKNOWN, and sparse dots for NO DETECTION.
3. THE State_Palette SHALL give every pair of distinct states a relative-luminance contrast ratio of at least 1.4 and SHALL give NO DETECTION the lowest relative luminance (parent R12.2).
4. THE State_Palette SHALL use no color with a hue between 75 and 165 degrees for any Room_State.
5. THE PWA SHALL show NO DETECTION rooms with the sub-label "Still needs a sweep".
6. THE PWA SHALL show no Banned_Word in any user-visible text.
7. WHEN a room's Confidence band is high, medium, or low, THE PWA SHALL render that room's fill at 100, 75, or 50 percent saturation and show the band and percentage (for example "LOW 34%"), with the pattern unchanged.
8. WHERE a room is uncalibrated, THE PWA SHALL render that room with the UNKNOWN treatment and an "Uncalibrated" chip (parent R1.5, R7.4).
9. WHERE a room is flagged simulated, THE PWA SHALL draw repeating "SIMULATED" text on that room's floor and a SIMULATED chip on its label (parent R10.5).

### Requirement 10: Always-Visible Header

**User Story:** As a responder, I want the disclaimer, recording status, and sensor health always on screen, so that I never forget the limits of the readout.

#### Acceptance Criteria

1. THE PWA SHALL show the disclaimer "Decision support only — does not replace a full search" on every screen, including the pairing and floor-plan error screens (parent R10.3, R21.4).
2. THE PWA SHALL show the Recording_Indicator text from the latest `recording` message on every screen after pairing (parent R15.7).
3. THE PWA SHALL show the Health_Chip with the `health.summary` text in the header, and WHEN the Health_Chip is tapped, THE PWA SHALL open a fault list showing each fault's cause and suggested action (parent R19.4).
4. WHILE the latest `room_states` message has `simulated: true`, THE PWA SHALL show the Simulated_Data_Badge "SIMULATED DATA" in the header (parent R10.5).
5. WHEN the system state is ALARM_ACTIVE_State, THE PWA SHALL set the `theme-color` meta tag to the alarm red, and WHEN the system state is IDLE_State, THE PWA SHALL restore the default `theme-color`.

### Requirement 11: Responder Workflow

**User Story:** As a responder, I want to see the next room to search, its details, and mark it searched in a couple of taps, so that I can work through the building quickly.

#### Acceptance Criteria

1. WHILE in Fire_Mode, THE Priority_List SHALL show every Flagged_Room with rank badge, room name, state label, confidence text, Age_Text or stale text, and a mark-searched control.
2. WHEN a responder taps a mark-searched control and then the confirm control, THE PWA SHALL call `POST /api/rooms/{room_id}/searched`, completing the action in at most 2 taps (parent R13.4).
3. WHILE a room's `searched` flag is true, THE PWA SHALL render that room's floor at 35 percent opacity with a "✓ SEARCHED" chip.
4. WHEN a responder taps a room on the floor plan or in the Priority_List, THE PWA SHALL open the Room_Sheet showing state, Confidence, last activity, `alarm_time_state`, link health, the Edge or Hub source badge, crew present, and a mark-searched control (parent R13.6, R37.2).
5. WHEN a responder taps a floor tab, THE PWA SHALL show that floor in 1 tap, and each floor tab SHALL show the count of unsearched Flagged_Rooms on that floor (parent R13.5).
6. WHEN the Priority_List is non-empty and every listed room is searched, THE PWA SHALL show the All_Searched_Banner (parent R13.7).
7. WHILE in Fire_Mode, THE PWA SHALL require no typing (parent R13.8).
8. THE PWA SHALL give the rank-1 room's badge a white halo ring that no other room's badge shows.

### Requirement 12: Stale Data and Hub Loss

**User Story:** As a responder, I want old data to look old, so that I never act on a reading that silently stopped updating.

#### Acceptance Criteria

1. WHILE a room's `stale` flag is true, THE PWA SHALL render that room with the UNKNOWN treatment and the text "last known <label of last_known_state>, <Age_Text of stale_age_s> ago" (parent R14.3).
2. WHEN 5 seconds have elapsed since `lastMessageAt`, THE PWA SHALL show the Hub_Lost_Banner (parent R19.8).
3. WHILE the Hub_Lost_Banner is shown, THE PWA SHALL grey every room and show "STALE — last known <label>" with the Age_Text since `lastMessageAt` on every room that has a last-known state.
4. WHEN a valid message arrives after hub loss, THE PWA SHALL remove the Hub_Lost_Banner and the hub-loss greying.
5. THE PWA SHALL show "Motion last seen <Age_Text> ago" from `last_seen` on every non-stale room in ALARM_ACTIVE_State.

### Requirement 13: Fire-Mode Entry

**User Story:** As a responder, I want an unmistakable switch into fire mode that lands me on the top room, so that I know where to start within seconds.

#### Acceptance Criteria

1. WHEN a `room_states` message with `system_state: "ALARM_ACTIVE"` arrives while the Store holds IDLE_State, THE PWA SHALL show the red header and "Recording (alarm)" within 300 milliseconds.
2. WHEN fire mode starts and `prefers-reduced-motion` is not set, THE PWA SHALL show a full-screen red flash lasting 1 second.
3. WHEN fire mode starts, THE PWA SHALL frame every Flagged_Room in view within 600 milliseconds and open the Priority_List to at least its first 3 rows, so that the rank-1 room is identifiable within 5 seconds (parent R13.3).
4. WHEN fire mode starts, THE PWA SHALL request a Screen Wake Lock, re-request the Wake Lock when the document becomes visible, and continue without error IF the Wake Lock API is unavailable or the request is rejected.
5. WHILE in Fire_Mode, THE Snapshot_Inset SHALL draw each room's `alarm_time_state` from the latest `room_states` message (parent R14.1, R27.4).
6. WHERE the snapshot inset is cut to a toggle (cut order item 3), THE PWA SHALL show the Snapshot_Inset only after the responder taps an "At alarm" toggle.

### Requirement 14: Normal-Mode Display

**User Story:** As the installer, I want the phone in normal mode to show the building and sensor health only, so that nothing about occupants is shown outside an incident.

#### Acceptance Criteria

1. WHILE the system state is IDLE_State, THE Hub_Web_Layer SHALL send `room_states` messages with an empty `rooms` array and an empty `ranking` array (parent R15.1, R15.2).
2. WHILE the system state is IDLE_State, THE Scene_Model SHALL produce no state label, rank badge, or occupancy pattern for any room, even IF a received message contains room entries.
3. WHILE the system state is IDLE_State, THE PWA SHALL show the floor plan with node status and link health from the latest `health` message.
4. WHEN the system state changes from ALARM_ACTIVE_State to IDLE_State, THE Store SHALL discard every held `room_states` room entry and `crew` tag entry.
5. THE PWA SHALL show no calibration or test-mode controls (parent R18.5).

### Requirement 15: Crew Markers [Should; cut order item 1]

**User Story:** As an incident commander, I want to see which room each tagged responder is in, with honest uncertainty, so that I know where crews are without false precision.

#### Acceptance Criteria

1. WHILE in Fire_Mode, WHEN a `crew` tag has `location_kind: "room"` with medium or high Confidence, THE PWA SHALL draw a Crew_Marker at that room's crew slot using only Crew_Palette colors and the tag-ID label (parent R26.1).
2. WHEN a `crew` tag has `location_kind` "near", THE PWA SHALL show a chip "<tag_id> · Near <room A> / <room B>" on the shared wall or door and SHALL draw no Crew_Marker inside any room (parent R25.5).
3. WHEN a `crew` tag has `location_kind` "between", THE PWA SHALL show a chip "<tag_id> · Between rooms" and SHALL draw no Crew_Marker inside any room (parent R25.6).
4. WHEN a `crew` tag has `marker: "hollow"`, THE PWA SHALL draw a hollow Crew_Marker at the last-heard room's crew slot with the text "Last heard <room>, <Age_Text> ago" (parent R25.7).
5. IF a `crew` tag has low Confidence, THEN THE PWA SHALL draw no single-room Crew_Marker for that tag.
6. THE PWA SHALL show each floor tab's crew count from `crew.floor_crew_counts` (parent R26.3).
7. WHERE a room's annotation is `responder_present` or `recent_motion_may_be_responder`, THE PWA SHALL show "Motion · responder present" or "recent motion may be responder" as label text only, without changing the room's fill, pattern, label, or rank (parent R27.1–R27.3).

### Requirement 16: Realistic 2D and 3D Rendering [3D: cut order item 4]

**User Story:** As a responder, I want the floor plan to look like the real building, so that I can match it to what I see.

#### Acceptance Criteria

1. THE Renderer_2D SHALL draw walls, door gaps with swing arcs, furniture outlines, nodes, link lines, room fills, patterns, and labels from the floor plan and Room_Descriptors.
2. WHERE the 3D renderer is included, THE Renderer_3D SHALL draw extruded walls cut to 1.0 m height, door openings, furniture blocks, nodes at their mounting height, and link beams, with an orthographic isometric camera.
3. WHERE the 3D renderer is included, THE Renderer_3D SHALL render state labels, confidence, and rank badges as HTML elements pinned to room centroids.
4. IF WebGL is unavailable, the WebGL context is lost, or the median frame time exceeds 33 milliseconds over 3 seconds, THEN THE PWA SHALL switch to the Renderer_2D and show "2D view".
5. THE Renderer_2D and the Renderer_3D SHALL anchor every state effect to the room centroid or the whole room floor and SHALL draw no person figure, footprint, heatmap, in-room trail, smoke, or fire particle.
6. WHEN a link's TX node is reported `tx_dead`, THE renderers SHALL draw that link as a broken red dashed line with a fault icon, and WHEN a link's RX node is offline, THE renderers SHALL hide that link and show "!" at the RX node.
7. WHILE `prefers-reduced-motion` is set, THE renderers SHALL show no animation.

### Requirement 17: On-Device Privacy

**User Story:** As an occupant, I want the phone to keep no record of the incident, so that losing the phone exposes nothing about who was in the building.

#### Acceptance Criteria

1. THE Service_Worker SHALL precache the App_Shell only and SHALL define no runtime caching route.
2. THE Service_Worker SHALL serve no response for `/api/*` or `/ws` from any cache.
3. THE PWA SHALL write no `room_states`, `crew`, `health`, or `recording` content to Cache Storage, IndexedDB, `localStorage`, or `sessionStorage`.
4. THE PWA SHALL write only the key `beacon.token` to `localStorage`.
5. IF the built JavaScript bundle contains a string matching the MAC-address pattern of Requirement 6.7, THEN the privacy test suite SHALL fail.

### Requirement 18: Offline, Self-Contained App Shell

**User Story:** As the team, I want the app to work with no internet, so that it runs at the venue on the hotspot alone.

#### Acceptance Criteria

1. THE PWA SHALL bundle every script, style, font, and icon and SHALL reference no external origin.
2. THE PWA SHALL bundle Atkinson Hyperlegible font files under their OFL license, and IF the font files are not available at build time, THEN THE PWA SHALL use the system font stack and the repository SHALL carry a TODO naming the missing files.
3. THE PWA SHALL provide a web app manifest with `display: standalone`, a dark `background_color`, and team-drawn icons at 192 and 512 pixels, a maskable icon, and an `apple-touch-icon`.
4. THE PWA SHALL contain no third-party insignia, emblem, or brand mark.
5. WHEN the installed PWA starts with no network, THE PWA SHALL show the App_Shell with the disclaimer and the Hub_Lost_Banner.

### Requirement 19: Accessibility

**User Story:** As a responder wearing gloves in poor light, I want large targets and readable text, so that I can use the app under stress.

#### Acceptance Criteria

1. THE PWA SHALL render every interactive element with a hit area of at least 56 × 56 CSS pixels (parent R12.3).
2. THE PWA SHALL give every room label, rank badge, and control an accessible name that includes the room name and state label.
3. THE PWA SHALL render text with a contrast ratio of at least 4.5:1 against its background (parent R12.4).

### Requirement 20: Hub Web Layer and State Source

**User Story:** As a developer, I want a small reusable web layer with a pluggable data source, so that the real pipeline can replace the mock without changing the PWA.

#### Acceptance Criteria

1. THE Hub_Web_Layer SHALL serve the built App_Shell from `hub/static` and SHALL return `index.html` for every non-API, non-asset path.
2. THE Hub_Web_Layer SHALL obtain room states, health, crew, and recording data only through the State_Source interface.
3. WHEN the State_Source publishes a message, THE Hub_Web_Layer SHALL broadcast that message to every authenticated WebSocket client within 200 milliseconds.
4. WHEN a Loopback_Client calls `POST /api/alarm/trigger` or `POST /api/incident/end`, THE Hub_Web_Layer SHALL forward the command to the State_Source and return the State_Source result.
5. IF `POST /api/rooms/{room_id}/searched` names a room the State_Source does not know, THEN THE Hub_Web_Layer SHALL return HTTP 404 and leave the system state unchanged.
6. THE Hub_Web_Layer SHALL write no Occupancy_Data to disk.

### Requirement 21: Mock Hub Scripted Incident

**User Story:** As the dashboard developer, I want a scripted incident that exercises every display case, so that I can build and record the demo before the sensors work.

#### Acceptance Criteria

1. THE Mock_Hub SHALL serve the Hub_Web_Layer with a scripted State_Source that sets `simulated: true` on every `room_states` message.
2. WHILE no alarm has been triggered, THE Mock_Hub SHALL publish IDLE_State messages carrying health only.
3. WHEN the alarm is triggered, THE Mock_Hub SHALL play a timeline in which R1 shows MOTION then POSSIBLE, RX2 goes offline so that R2 becomes UNKNOWN with a stale last-known state, and tag E1 moves from R1 through a "near" phase to R2 and then goes silent for at least 10 seconds.
4. WHEN a Searched_Mark arrives, THE Mock_Hub SHALL set that room's `searched` flag and rank that room after every unsearched room, preserving Search_Priority order within each group (parent R9.5).
5. WHEN End incident is called, THE Mock_Hub SHALL return to IDLE_State and reset the timeline.

### Requirement 22: Performance Budget

**User Story:** As a responder on a mid-range phone, I want the plan to stay smooth, so that the app is responsive during an incident.

#### Acceptance Criteria

1. THE PWA SHALL keep its total gzipped JavaScript at or below 350 KB.
2. THE Renderer_3D SHALL cap the device pixel ratio at 2 and SHALL render frames only while a message has just arrived, an animation is active, or a gesture is in progress.
3. WHILE the document is hidden, THE Renderer_3D SHALL render no frames.

### Requirement 23: Build, Pinning, Documentation, and Kiro Artifacts

**User Story:** As a judge, I want to run the dashboard from the repository with clear steps, so that I can verify the demo.

#### Acceptance Criteria

1. THE repository SHALL pin every dependency in `dashboard/package.json` and `hub/requirements.txt` to an exact version with no range operator.
2. THE repository SHALL commit the built `hub/static` output.
3. THE README SHALL describe how to build the PWA, run the hub and the Mock_Hub, create the mkcert certificate, trust the root CA on the iPhone, install the PWA, and pair the phone.
4. THE repository SHALL contain `.kiro/steering/ui.md` stating the State_Palette, the state encoding, the Banned_Words, the no-person-figure and no-smoke rule, and the 56-pixel target rule.
5. THE repository SHALL record decisions D1 to D5 and the Kiro usage for this feature in `CONTEXT.md`.
