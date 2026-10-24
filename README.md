# RoomSense

## Dashboard (PWA)

The dashboard is decision support. It never declares a room empty or clear.

### Prerequisites

- Python 3.12+ (tested on 3.14)
- Node 20+ (only needed to rebuild; `hub/static` is committed)
- [mkcert](https://github.com/FiloSottile/mkcert) (only for the phone)

### Laptop demo

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r hub/requirements.txt
.venv\Scripts\python tools/mock_hub.py
```

Open http://127.0.0.1:8443 (plain HTTP when no certs are present). Trigger the simulated alarm from the laptop.

### Rebuild the dashboard

```powershell
npm --prefix dashboard ci
npm --prefix dashboard run build
```

### Phone (iPhone)

1. Turn on Windows Mobile Hotspot on the **5 GHz** band. This keeps phone traffic off the 2.4 GHz sensing channel.
2. Issue a cert with mkcert (about 10 minutes, do it before the event):
   ```powershell
   mkcert -install
   mkcert -cert-file hub/certs/hub.pem -key-file hub/certs/hub-key.pem 192.168.137.1 localhost 127.0.0.1
   ```
3. AirDrop `rootCA.pem` (from the folder `mkcert -CAROOT` prints) to the iPhone and open it.
4. Settings → General → VPN & Device Management → install the profile.
5. Settings → General → About → Certificate Trust Settings → enable full trust for the mkcert root. Without this, Safari warns and the service worker won't register.
6. Check that https://192.168.137.1:8443 opens in Safari with no warning. If the hotspot IP differs, check it with `ipconfig` and reissue the cert.
7. In Safari: Share → Add to Home Screen.
8. Open the installed app (not Safari; storage is separate) and enter the 6-digit code shown on the laptop under "Pair a phone".
9. On iOS older than 18.4, set Auto-Lock to Never.

"Revoke phones" on the laptop signs out all paired phones.

The alarm trigger and End incident only work from the laptop. The phone can mark rooms searched.

### Security notes

- Every API route and the WebSocket require a token.
- The hub listens only on 127.0.0.1 and the hotspot address, never 0.0.0.0. Don't expose it to the internet.
- Certs and tokens are git-ignored: `hub/certs/`, `hub/config/secrets.json`, `hub/.env`.
- Residual risks: anyone on the hotspot can reach the app shell and the pairing endpoint (rate-limited). The 6-digit code is valid for 2 minutes and single use.

### Tests

```powershell
npm --prefix dashboard run test
.venv\Scripts\python -m pytest hub/tests tools/tests -q   # property tests take ~5 min
python tools/check_pins.py
python tools/scan_ui.py
```
