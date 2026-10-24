# RoomSense node firmware

One firmware image for every board. Each board's job is set over serial and saved in flash. It follows the RoomSense design in `.kiro/specs/roomsense-occupancy-tool/design.md`.

| Role | RoomSense spec name | What it does |
|------|---------------------|--------------|
| `tx` | TX_Node (master) | Sends a numbered packet to its paired receiver (or to everyone) 100 times a second, at an OFDM rate so the receiver gets CSI. Prints nothing while running |
| `rx` | RX_Node (slave) | Listens to its paired transmitter, turns each packet's CSI into 64 amplitudes, prints one `CSI` line per packet, a `HB` heartbeat every second, and `TAG` summaries for responder tags |
| `tag` | Responder_Tag | Broadcasts its ID about 10 times a second with timing jitter and blinks an LED. Prints nothing while running |

The text format on the serial port (what the pipeline, model, dashboard and simulator read) is in [docs/serial-protocol.md](docs/serial-protocol.md), which restates `design.md`. Read that, not the C code.

## Status

- Builds cleanly for the classic **ESP32** (the target) and, earlier, the **ESP32-C3**, with ESP-IDF v6.0. The prebuilt image is for the classic ESP32; build from source for a C3.
- **Tested on hardware so far:** a transmitter on a power bank and two receivers (classic ESP32 boards). Receiver 1 gets about 105 CSI lines/s with no loss and the heartbeat matches the design. Receiver 2, paired to the same transmitter but not the one it unicasts to, also hears it (about 96 lines/s, a few percent loss). Hand-over-antenna and walking tests change the signal. Settings survive reboots; `SET`, `GET`, `PING`, `REBOOT` and `FACTORY_RESET` work, including rejecting bad values.
- **Not yet tested:** tags, a long run, battery-powered transmitter over time, two transmitter/receiver pairs at once, and the offset used to read the packet counter beyond "counters arrive in order with no gaps".
- **Not built:** `EDGE` and `TRAINING` receiver modes, `RSST`/`FEAT` lines, `peers`, the annunciator, and UDP transport.

## Flash a board (no ESP-IDF needed)

The Arduino IDE cannot upload this firmware (it is an ESP-IDF program, not an Arduino sketch), but it already installed `esptool`, which can. `flash.ps1` finds it for you.

```powershell
cd firmware
.\flash.ps1 -Port COM3
```

Not sure which chip you have? Run `esptool --port COM3 chip-id` (it prints the chip type). `ESP32 Dev Module` in the Arduino IDE means a classic ESP32. If flashing fails to connect, hold the BOOT button while it starts, or lower the speed with `-Baud 115200`.

Close the Arduino Serial Monitor before flashing or capturing. Only one program can hold a serial port.

## Set up a board

Open the board's port at **921600 baud** with line ending **Newline** (the Arduino Serial Monitor works), then type commands. Settings are saved in flash and survive power loss; they apply after `REBOOT`. Full list: [docs/serial-protocol.md](docs/serial-protocol.md).

```
GET                              prints settings, plus this board's mac
SET node_id=RX1 room_id=R1 role=rx
SET paired_tx=<transmitter mac>
SET tags=E1,E2
REBOOT
```

### Pairing one transmitter with one receiver

1. Transmitter: `SET node_id=TX1 room_id=R1 role=tx`, `GET` (note its `mac`), `REBOOT`.
2. Receiver: `SET node_id=RX1 room_id=R1 role=rx paired_tx=<TX mac>`, `GET` (note its `mac`), `REBOOT`.
3. Transmitter: `SET peer=<RX mac>`, `REBOOT`. (Optional: without it the transmitter broadcasts, which also works.)

Power the transmitter from any USB supply or power bank. Plug the receiver into the laptop. Within a few seconds the receiver should print `CSI,...` lines and its heartbeat `measured_pps` should be near 100.

### The RoomSense two-room demo

Two transmitter/receiver pairs plus one tag, five boards in total:

| Board | Settings |
|-------|----------|
| TX1 | `role=tx node_id=TX1 room_id=R1 peer=<RX1 mac>` |
| TX2 | `role=tx node_id=TX2 room_id=R2 peer=<RX2 mac>` |
| RX1 | `role=rx node_id=RX1 room_id=R1 paired_tx=<TX1 mac> tags=E1` |
| RX2 | `role=rx node_id=RX2 room_id=R2 paired_tx=<TX2 mac> tags=E1` |
| Tag | `role=tag node_id=TAG1 tag_id=E1` |

All boards must be on the same channel (default 11; `SET channel=1`, `6` or `11`). Pick the quietest of 1, 6 and 11 at the venue.

## See it working (live viewer)

```powershell
cd firmware\tools
.\.venv\Scripts\python.exe -m roomsense_hub.viewer --port COM3
```

It opens `http://127.0.0.1:8765` and shows, for each receiver, its health (from the heartbeat), packet rate and loss, a scrolling picture of the signal (subcarrier up the side, time across, brighter = stronger), and an activity line with a MOTION / QUIET badge. Walk between the two boards and the picture changes. The badge is a simple demo indicator, not the detection model; "quiet" never means a room is empty. It listens on 127.0.0.1 only and stores nothing. Close it (Ctrl+C) before flashing or recording, because it holds the serial port. `--replay tests\fixtures\sample_capture.log` shows it without hardware.

## Read the stream and record training data

```powershell
cd firmware\tools
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -e .
.\.venv\Scripts\python.exe -m pytest                      # protocol tests
copy authorized_installers.example.txt authorized_installers.txt   # then edit it
.\.venv\Scripts\rs-capture.exe --port COM3 --port COM4 --label moving --installer alice --consent
```

`rs-capture` writes one CSV per class (`empty`, `moving`, `still_present`) under `firmware/tools/data/` (git-ignored). Recording is limited to allow-listed installers and consenting people (requirements 17 and 21.5). Other code should import `roomsense_hub` (`parse_line`, `format_record`) instead of writing a second parser.

## Motion location map (floor plan, boards placed in the app)

`rs-view` shows a floor plan with every board on it and estimates *where* motion is from which links (transmitter-to-receiver lines) are disturbed: a zone about 1 to 2 m across, one moving person at a time, never a precise position. It runs on the unchanged firmware above.

**1. Try it with no boards** (from `firmware	ools`, venv set up as above):

```powershell
.\.venv\Scripts\rs-view.exe --simulate
```

A virtual person walks a loop, pauses, and walks again. This checks the page, not real accuracy.

**2. Flash the boards** with `.\flash.ps1 -Port COMx`. `.\.venv\Scripts\rs-setup.exe ports` shows which COM port is the board.

**3. Configure them** (close any serial monitor or rs-view first). Transmitters first, so their MACs are known:

```powershell
.\.venv\Scripts\rs-setup.exe tx COM8 --id TX1
.\.venv\Scripts\rs-setup.exe rx COM8 --id RX1 --tx TX1     # the next board; same port if you swap boards
.\.venv\Scripts\rs-setup.exe rx COM8 --id RX2 --tx TX1
.\.venv\Scripts\rs-setup.exe info COM8                     # check a board
```

Transmitter MACs are saved in `tools/boards.json` (git-ignored). Label each board with its name. One transmitter can serve several receivers; each receiver listens to one transmitter.

**4. Run the app:**

```powershell
.\.venv\Scripts\rs-view.exe
```

It reads every ESP32 plugged into the laptop, including ones plugged in later. Transmitters only need power (charger or power bank); every receiver needs a USB data cable to the laptop (use a hub). The **Floor plan** card lists every board: receivers with their live state, transmitters with which receivers hear them (a transmitter has no cable, so that is how you know it is on).

**5. Put the boards on the plan, in the app:**

- **Upload floor plan** (PNG, JPEG, WebP or GIF), then **Set scale**: click both ends of something you know the length of and type it (`13 ft` or `4.2 m`). Without a picture, **Set area size** gives a blank grid.
- For each board, press **Place** and click where it stands. Drag a board to move it; **x** removes it.
- A link appears once a receiver *and* its transmitter are placed. Links that cross at different angles locate motion; a single link only says "motion somewhere along this line".

The picture and positions are saved in `tools/site/` (git-ignored, since a real building's plan can be sensitive) and come back on the next start.

Leave the room empty for the first ~5 seconds after starting (each link learns its quiet level; press **Reset baseline** to relearn), then walk through it. `--port COMx` reads only the ports you list; `--layout FILE` uses fixed positions from a JSON file instead of the app.

## Relay mode (EXPERIMENTAL, branch `feat/relay-experimental` only)

Only one board, the **gateway transmitter**, is cabled to the laptop; up to 4 receivers send their lines to it over the air (ESP-NOW) and run on any power source. The viewer reads the gateway's one port and sees the same lines as before.

**Not merged to main on purpose:** it forwards raw CSI over the air, which conflicts with Privacy Rule 1 in `CONTEXT.md`, and the relay traffic shares the sensing channel (its effect on detection is not measured). See the open question there.

The prebuilt image on this branch is the one built from commit 8e827f8 (relay mode); the later firmware cleanup on main changed no behaviour. Rebuild from this branch's source with ESP-IDF to refresh it.

```powershell
.\flash.ps1 -Port COMx                                         # every board gets this branch's image
cd tools
.\.venv\Scripts\rs-setup.exe tx COM8 --id TX1                     # the gateway, outside the room, stays on USB
.\.venv\Scripts\rs-setup.exe rx COM8 --id RX1 --tx TX1 --relay-to TX1   # each receiver (swap boards on the same port)
.\.venv\Scripts\rs-setup.exe gateway COM8 --id TX1                # last, with TX1 plugged in again
.\.venv\Scripts\rs-view.exe --port COM8
```

`rs-setup gateway` lists the receivers that relay to it (from `boards.json`, at most 4) and lowers the gateway's rate to 50 packets/s: four receivers at 100/s would be about 130 KB/s, more than the gateway's 921600-baud USB link carries (about 92 KB/s). A receiver may listen to a different transmitter than the one it relays to. The viewer judges packet loss against what each board says it received, so 50/s is not shown as loss.

## Build from source

Needs ESP-IDF v6.0 (install with Espressif's `eim`, with the `mcp` feature if you want Kiro to drive the build). The first build downloads the `esp_csi_gain_ctrl` component, so it needs internet.

```powershell
cd firmware
idf.py set-target esp32
idf.py build
```

The boards are classic ESP32 ("ESP32 Dev Module"). The code also builds for other ESP32 chips with CSI support (`idf.py set-target <chip>`), but only the classic ESP32 has been tested.

After changing the code, rebuild and refresh the committed image: `esptool --chip esp32 merge-bin -o prebuilt/roomsense-esp32.bin @flash_args` from the build folder.

## Layout

| Path | What |
|------|------|
| `main/` | The firmware (config, radio, tx, rx, tag, console, protocol formatting) |
| `docs/serial-protocol.md` | The serial contract, restated from design.md |
| `tools/` | Python reader, parser, and training-data recorder, with tests |
| `prebuilt/` | Single-file flash image for `flash.ps1` |
| `flash.ps1` | Flash helper that uses the Arduino IDE's esptool |

## Credits

CSI capture follows Espressif's [esp-csi](https://github.com/espressif/esp-csi) `csi_send` and `csi_recv` examples (Apache-2.0). Receive-gain compensation (on chips that support it) comes from Espressif's `esp_csi_gain_ctrl` component, downloaded at build time.
