# RoomSense dashboard (PWA)

Phone-installable responder dashboard plus the FastAPI hub web layer that serves it. Built to `.kiro/specs/pwa-dashboard/requirements.md` and the parent spec `.kiro/specs/roomsense-occupancy-tool/`.

> Provenance: this is the backup implementation on branch `claude/pwa-backup`, written by Claude Code in parallel with the Kiro build. It follows the same endpoints, file paths and message shapes as the Kiro spec, so either version can replace the other.

## What's here

| Path | What it is |
|---|---|
| `dashboard/` | Vite + TypeScript + Preact app. three.js isometric 3D plan, SVG 2D fallback. |
| `dashboard/src/scene/model.ts` | Pure view model: floor plan + hub messages + time → what to draw. All display rules live here. |
| `dashboard/src/render3d/` | three.js renderer (walls, doors, furniture, nodes, link beams, state patterns, HTML labels). |
| `dashboard/src/render2d/` | SVG renderer; also the alarm-time snapshot inset. |
| `hub/` | FastAPI web layer: pairing, tokens, laptop-only controls, `/api/floorplan`, WebSocket, static app. |
| `hub/config/floorplan.json` | The floor plan (meters). Room 101 is generated from the DXF (below); other rooms are hand-edited. Edit and reload the app; no rebuild needed. |
| `hub/static/` | Built app, committed so the hub runs without Node. |
| `tools/mock_hub.py` | Hub with a scripted incident; every message is labeled SIMULATED. |
| `tools/live_hub.py` | Hub on real receivers (or `--simulate-boards` / `--replay`). |
| `hub/live_source.py`, `hub/room_engine.py` | Live data: receivers → link states (via `firmware/tools/roomsense_hub`) → room states. |
| `tools/dxf_to_floorplan.py` | Builds Room 101 in the floor plan from `floor plans/conference_room.dxf`. |

## Run it on the laptop (no phone, no certs)

```bash
hub/.venv/Scripts/python tools/mock_hub.py --host 127.0.0.1 --port 8443
```

Open `http://127.0.0.1:8443`. The laptop gets a token automatically and shows the presenter controls: **Trigger alarm (demo)**, **End incident…**, **Pair a phone**, **Revoke phones…**. Use `--speed 4` to run the scripted incident four times faster.

First-time Python setup: `python -m venv hub/.venv && hub/.venv/Scripts/python -m pip install -r hub/requirements.txt`

## Run it on real boards

Uses the six-board, one-room setup from `firmware/README.md` ("Motion location map"): TX1 and TX2 in opposite corners, RX1–RX4 on the walls. Flash and configure the boards as described there; keep the names **TX1, TX2, RX1–RX4**, because the floor plan matches receivers to Room 101 by name. A board's `room_id` setting doesn't matter (a mismatch is logged once).

1. Plug the four receivers into the laptop (powered USB hub) and find their ports with `firmware\tools\.venv\Scripts\rs-setup.exe ports`. Close `rs-view` and any serial monitor first; only one program can hold a port.
2. Start the hub on the receivers:
   ```powershell
   hub/.venv/Scripts/python tools/live_hub.py --port COM8 --port COM9 --port COM10 --port COM11 --hold-s 60
   ```
   - `--hold-s` is how long a room stays POSSIBLE after motion stops. The spec says 300 s; 60 s keeps a demo moving.
   - Floor 2 (and Storage) stay SIMULATED and labeled so. Add `--no-sim` to show Room 101 only.
3. **Leave the room empty for the first ~10 s** so each link learns its quiet level. Until a link has learned it, the room shows UNKNOWN · Uncalibrated.
4. Open the dashboard as usual (laptop `https://localhost:8443`, phone over the iPhone hotspot) and trigger the alarm.

No boards yet? `tools/live_hub.py --simulate-boards` runs the same pipeline on simulated receivers (a person walking loops around the room), and `--replay firmware/tools/tests/fixtures/sample_capture.log` replays a real capture.

How a room's state is decided (`hub/room_engine.py`, the parent design's rules on top of the viewer's per-link MOTION/QUIET measure):

- **MOTION:** any link in motion for 2 of the last 3 ticks.
- **POSSIBLE:** motion stopped less than `--hold-s` ago, or the room hasn't been watched quietly for a full hold yet.
- **NO DETECTION:** every link healthy and quiet for a full hold. Quiet is never treated as empty.
- **UNKNOWN:** no usable link (no heartbeat for 10 s, no packets for 2 s, packet rate under 20/s, or a weak or flat signal). Shows the last known state and how long ago; after links come back it stays UNKNOWN for 10 s.
- **Confidence is a heuristic** (motion margin × packet-rate quality, capped LOW when a heartbeat is late). It is not a trained model; say so in the demo.
- Keep other heavy programs closed on the hub laptop. If packets are delayed by more than 2 s, rooms correctly drop to UNKNOWN.

### Update Room 101 from the DXF

```powershell
hub/.venv/Scripts/python tools/dxf_to_floorplan.py "floor plans/conference_room.dxf" --room-id R1 --height 9ft4in --layout firmware/tools/layouts/demo-room.json --write hub/config/floorplan.json
```

The DXF is in inches with the origin at the room's inside bottom-left corner. It draws the room 114 in deep, but the measured room is 112 in (9 ft 4 in), so `--height 9ft4in` corrects it and prints a warning. Board positions come from `demo-room.json` (feet from the top-left corner); measure the real placement and update that file, then rerun.

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
- **Privacy:** the service worker caches the app's own files only, with no runtime caching. Room and crew data live only in memory and are dropped when the incident ends. The only thing written to `localStorage` is `roomsense.token`.
- **3D fallback:** if WebGL is missing, the graphics context is lost, or frames take over 33 ms, the app switches to the 2D view and says why.
