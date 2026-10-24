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
- **Tested on hardware so far (one ESP32 as a receiver, no transmitter yet):** it flashes, boots, prints design-format `HB` lines that the Python parser accepts, keeps its settings across reboots, and handles `SET`, `GET`, `PING`, `REBOOT` and `FACTORY_RESET`, including rejecting bad values.
- **Not yet tested:** a transmitter talking to a receiver, receiving CSI, the offset used to read the packet counter from the frame, and tags. The first two-board test is milestone M1.
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

## Build from source

Needs ESP-IDF v6.0 (install with Espressif's `eim`, with the `mcp` feature if you want Kiro to drive the build). The first build downloads the `esp_csi_gain_ctrl` component, so it needs internet.

```powershell
cd firmware
idf.py set-target esp32            # or esp32c3
idf.py build
```

For a C3 board that uses the chip's built-in USB instead of a USB-to-serial chip:

```powershell
idf.py -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.usbserial" set-target esp32c3
```

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
