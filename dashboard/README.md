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
| `hub/config/floorplan.json` | The hand-edited floor plan (meters). Edit and reload the app; no rebuild needed. |
| `hub/static/` | Built app, committed so the hub runs without Node. |
| `tools/mock_hub.py` | Hub with a scripted incident; every message is labeled SIMULATED. |

## Run it on the laptop (no phone, no certs)

```bash
hub/.venv/Scripts/python tools/mock_hub.py --host 127.0.0.1 --port 8443
```

Open `http://127.0.0.1:8443`. The laptop gets a token automatically and shows the presenter controls: **Trigger alarm (demo)**, **End incident…**, **Pair a phone**, **Revoke phones…**. Use `--speed 4` to run the scripted incident four times faster.

First-time Python setup: `python -m venv hub/.venv && hub/.venv/Scripts/python -m pip install -r hub/requirements.txt`

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
