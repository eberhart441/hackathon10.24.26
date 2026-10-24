# Beacon dashboard (PWA)

Phone-installable responder dashboard plus the FastAPI hub web layer that serves it. Built to `.kiro/specs/pwa-dashboard/requirements.md` and the parent spec `.kiro/specs/beacon-occupancy-tool/`.

> Provenance: this is the backup implementation on branch `claude/pwa-backup`, written by Claude Code in parallel with the Kiro build. It follows the same endpoints, file paths and message shapes as the Kiro spec, so either version can replace the other.

## What's here

| Path | What it is |
|---|---|
| `dashboard/` | Vite + TypeScript + Preact app. three.js isometric 3D plan, SVG 2D fallback. |
| `dashboard/src/scene/model.ts` | Pure view model: floor plan + hub messages + time → what to draw. All display rules live here. |
| `dashboard/src/render3d/` | three.js renderer (walls, doors, furniture, nodes, link beams, state patterns, HTML labels). |
| `dashboard/src/render2d/` | SVG renderer; also the alarm-time snapshot inset. |
| `hub/` | FastAPI web layer: pairing, tokens, laptop-only controls, `/api/floorplan`, WebSocket, static app. |
| `hub/config/floorplan.json` | The floor plan (meters): Room 1, Room 2 and the hallway from `floor plans/walls_only.dxf`. Walls and boards are generated (below); the rooms are hand-edited. `hub/config-two-rooms/floorplan.json` is the same plan. Edit and reload the app; no rebuild needed. |
| `hub/static/` | Built app, committed so the hub runs without Node. |
| `tools/mock_hub.py` | Hub with a scripted incident; every message is labeled SIMULATED. |
| `tools/live_hub.py` | Hub on real receivers (or `--simulate-boards` / `--replay`). |
| `hub/live_source.py`, `hub/room_engine.py` | Live data: receivers → link states (via `firmware/tools/beacon_hub`) → room states. |
| `tools/walls_to_floorplan.py` | Puts the walls of `floor plans/walls_only.dxf` and the boards of an rs-view layout into the floor plan. |
| `tools/dxf_to_floorplan.py` | Older one-room converter for `floor plans/conference_room.dxf` (not used by the current plan). |

## Run it on the laptop (no phone, no certs)

```bash
hub/.venv/Scripts/python tools/mock_hub.py --host 127.0.0.1 --port 8443
```

Open `http://127.0.0.1:8443`. The laptop gets a token automatically and shows the presenter controls: **Trigger alarm (demo)**, **End incident…**, **Pair a phone**, **Revoke phones…**. Use `--speed 4` to run the scripted incident four times faster.

First-time Python setup: `python -m venv hub/.venv && hub/.venv/Scripts/python -m pip install -r hub/requirements.txt`

## Run it on real boards

Uses the two-room demo layout (`firmware/tools/layouts/two-rooms.json`): TX1 in the hallway just outside Room 1's door, RX2 and RX3 on Room 1's back wall, RX1 at the far end of the hallway. Room 2 has no sensors and shows UNKNOWN · "No sensors in this room" for the whole incident, so it is still ranked for a search. Keep the names **TX1, RX1–RX3**, because the floor plan matches receivers to rooms by name. A board's `room_id` setting doesn't matter (a mismatch is logged once).

1. Plug the four receivers into the laptop (powered USB hub) and find their ports with `firmware\tools\.venv\Scripts\rs-setup.exe ports`. Close `rs-view` and any serial monitor first; only one program can hold a port.
2. Start the hub on the receivers:
   ```powershell
   hub/.venv/Scripts/python tools/live_hub.py --port COM8 --port COM9 --port COM10 --port COM11 --hold-s 60
   ```
   - `--hold-s` is how long a room stays POSSIBLE after motion stops. The spec says 300 s; 60 s keeps a demo moving.
3. **Leave the room empty for the first ~10 s** so each link learns its quiet level. Until a link has learned it, the room shows UNKNOWN · Uncalibrated.
4. Open the dashboard as usual (laptop `https://localhost:8443`, phone over the iPhone hotspot) and trigger the alarm.

No boards yet? `tools/live_hub.py --simulate-boards` runs the same pipeline on simulated receivers (a person walking loops around the room), and `--replay firmware/tools/tests/fixtures/sample_capture.log` replays a real capture. Use `--layout firmware/tools/layouts/two-rooms.json` with `--simulate-boards` to match the floor plan. Add `--simulate-tag` for a responder tag E1 heard by Room 1's receivers.

### The phone view

The iPhone (any device that isn't the hub laptop) gets the floor plan and nothing else; the laptop keeps the full 3D presenter view. Open `https://localhost:8443/?view=phone&tag=E1` on the laptop to see the phone view there.

- **Only the rooms:** each room is drawn with its colour and pattern by state and carries its own label inside it: search-priority number, name, state, and one status line ("Motion last seen 0:42 ago", "Still needs a sweep", "No sensors in this room", "Searched", or "STALE — last known …" when the hub is lost). Walls are the DXF's. There are no buttons and no text outside the rooms; fire mode adds a red frame, and simulated data is hatched SIMULATED inside every room.
- **You are here:** the phone is bound to the responder tag its holder carries (type it on the pairing screen, or open the app once with `?tag=E1`; `?tag=` unbinds). That tag shows as a white **YOU** marker with a pulse at the room's crew spot (a room, never a measured position). At low confidence it shows "YOU · Near Room 1 / Hallway" between the two rooms; a tag not heard for 10 s becomes a hollow marker where it was last heard. Other responders show as their tag ids. The phone's own position is never sensed: no phone radio is sniffed, and GPS cannot resolve rooms indoors, so location comes only from the tag. Tags are located only during an incident, so the marker appears once the alarm is triggered.
- The plan follows the floor of your tag, else the floor of the first room still to search.

Marking rooms searched and the room sheets stay on the laptop.

**Responder tags:** flash a board with `role=tag tag_id=E1` (see `firmware/README.md`) and add `tags=E1` to every receiver. The hub locates the tag room by room from the receivers' `TAG` lines (`hub/tag_locator.py`, the parent design's algorithm). Low confidence shows "near A / B" or "between rooms", never one room. Tags are tracked only during an incident and forgotten when it ends. With every receiver in one room, the tag can only ever be "in Room 101"; telling rooms apart needs receivers in more than one room.

How a room's state is decided (`hub/room_engine.py`, the parent design's rules on top of the viewer's per-link MOTION/QUIET measure):

- **MOTION:** any link in motion for 2 of the last 3 ticks.
- **POSSIBLE:** motion stopped less than `--hold-s` ago, or the room hasn't been watched quietly for a full hold yet.
- **NO DETECTION:** every link healthy and quiet for a full hold. Quiet is never treated as empty.
- **UNKNOWN:** no usable link (no heartbeat for 10 s, no packets for 2 s, packet rate under 20/s, a weak or flat signal, or a receiver the viewer would leave out: losing packets, glitching, or clipping), or no receiver in the room at all. Shows the last known state and how long ago; after links come back it stays UNKNOWN for 10 s.
- **Confidence is a heuristic** (motion margin × packet-rate quality, capped LOW when a heartbeat is late). It is not a trained model; say so in the demo.
- Keep other heavy programs closed on the hub laptop. If packets are delayed by more than 2 s, rooms correctly drop to UNKNOWN.

### Update the floor plan from the walls-only DXF

```powershell
hub/.venv/Scripts/python tools/walls_to_floorplan.py "floor plans/walls_only.dxf" --layout firmware/tools/layouts/two-rooms.json --layout-origin 0 -4.5 --write hub/config/floorplan.json
copy hub\config\floorplan.json hub\config-two-rooms\floorplan.json
```

The DXF is in inches. Its two wall loops become the floor's `walls` (the dashboard fills the space between them, so wall thickness and door gaps are the drawing's), with the floor origin at the drawing's bottom-left corner. Board positions come from `two-rooms.json` (feet from Room 1's top-left inside corner, which is DXF (0, -4.5)); each board is put in the room whose polygon contains it. The rooms themselves are hand-edited in `floorplan.json`, because a walls-only drawing does not say where a room ends and the hallway begins. `hub/tests/test_walls_to_floorplan.py` checks the committed plan against the DXF.

## Run it for the iPhone

The phone needs HTTPS, otherwise iOS won't install the app or run its service worker.

**Once, before the event (about 10 minutes):**

1. Install mkcert on the laptop, then run `mkcert -install`.
2. Run the `mkcert -cert-file …` command shown in `hub/.env.example`. It covers `localhost`, the Windows hotspot address, and the iPhone hotspot range `172.20.10.2`–`.14`.
3. Run `mkcert -CAROOT` to find `rootCA.pem`. AirDrop or email that file to the iPhone and open it.
4. iPhone: **Settings → General → VPN & Device Management**, then install the profile.
5. iPhone: **Settings → General → About → Certificate Trust Settings**, then turn on full trust for the mkcert root. If you skip this step, Safari still warns and the app won't install properly.
6. Copy `hub/.env.example` to `hub/.env`.

**At the venue:**

1. On the iPhone, turn on **Settings → Personal Hotspot → Allow Others to Join**. Leave **Maximize Compatibility** off so the hotspot stays on 5 GHz, away from the 2.4 GHz sensing channel.
2. Join the laptop to the iPhone's hotspot, over Wi-Fi or a USB cable. Run `ipconfig | findstr "172.20.10"` to get the laptop's address, for example `172.20.10.2`.
3. On the laptop, run `hub/.venv/Scripts/python tools/mock_hub.py`. Warnings for the `172.20.10.x` addresses the laptop doesn't have are expected; look for `Listening on https://172.20.10.x:8443`.
4. On the iPhone, open `https://<laptop address>:8443` in Safari, then **Share → Add to Home Screen**.

   (Windows Mobile Hotspot at `192.168.137.1` also works on some machines; our iPhone could never finish joining it.)
5. Open the installed app. It shows **Pair this phone**.
6. On the laptop dashboard, tap **Pair a phone** and type the 6-digit code into the phone. The code is valid for 2 minutes and works once.
7. The phone stays paired across hub restarts. **Revoke phones…** on the laptop signs every phone out.

The phone can view everything and mark rooms searched. The alarm trigger and End incident work only on the laptop; the hub returns 403 if any other device calls them.

## Develop

```bash
cd dashboard
npm ci
npm run dev        # http://127.0.0.1:5173, proxies /api and /ws to HUB_URL (default http://127.0.0.1:8443)
npm test           # Vitest + fast-check property tests (model, palette, validator, parser, privacy, wording)
npm run build      # type-check, then build into ../hub/static
node scripts/make-icons.mjs   # regenerate the app icons (team-drawn, no third-party art)
```

Hub tests: `hub/.venv/Scripts/python -m pytest hub/tests -q`

## Display rules the code enforces

- **States:** only four labels are ever shown: MOTION, POSSIBLE, UNKNOWN, NO DETECTION. Each has a color, an icon, a text label and a floor pattern (solid, hatch, cross-hatch, dots), so states stay distinguishable in grayscale. NO DETECTION is never green and always says "Still needs a sweep".
- **Wording:** no "empty", "clear" or "safe" anywhere in the UI. A test scans the source for these words.
- **Ranking:** the priority list is the hub's `ranking`, filtered to flagged rooms. The app never re-sorts it. Rank 1 gets the halo.
- **Stale data:** a stale or uncalibrated room is drawn as UNKNOWN with "last known …, m:ss ago". After 5 s with no hub message, a full-width HUB LOST banner appears and every room is greyed.
- **Room-level only:** motion rings start at the room center. There are no person figures, footprints, heatmaps or smoke. Crew markers use only white and black. A low-confidence crew location shows "Near A / B" or "Between rooms", never a single room.
- **Privacy:** the service worker caches the app's own files only, with no runtime caching. Room and crew data live only in memory and are dropped when the incident ends. The only thing written to `localStorage` is `beacon.token`.
- **3D fallback:** if WebGL is missing, the graphics context is lost, or frames take over 33 ms, the app switches to the 2D view and says why.
