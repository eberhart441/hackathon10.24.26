# RoomSense node firmware

One firmware image for every board. Each board's job is set over serial and saved in flash:

| Role | RoomSense spec name | What it does |
|------|---------------------|--------------|
| `tx` | TX_Node (master) | Broadcasts a counter packet 100 times a second on a fixed channel |
| `rx` | RX_Node (slave) | Listens to its paired `tx`, turns each packet's CSI into 64 amplitudes, prints one line per packet; also reports responder tags |
| `tag` | Responder_Tag | Broadcasts its ID about 10 times a second and blinks an LED |

The text format on the serial port (what the pipeline, model, dashboard and simulator read) is the contract in [docs/serial-protocol.md](docs/serial-protocol.md). Read that, not the C code.

## Status

- **Status:** Builds cleanly for **ESP32** and **ESP32-C3** with ESP-IDF v6.0.
- **Tested on hardware so far (one classic ESP32, receiver role, no transmitter yet):** it flashes, boots, prints valid `BOOT` and `HB` lines that the Python parser accepts, and answers `PING`, `CFG GET`, `CFG SET` (with validation) and unknown commands correctly. **Not yet tested:** the transmitter, receiving CSI from a transmitter, tags, and the frame offset used to read the packet counter. The first two-board test is milestone M1.

## Flash a board (no ESP-IDF needed)

The Arduino IDE cannot upload this firmware (it is an ESP-IDF program, not an Arduino sketch), but it already installed `esptool`, which can. `flash.ps1` finds it for you.

```powershell
cd firmware
.\flash.ps1 -Port COM5                 # classic ESP32 (the Arduino "ESP32 Dev Module")
.\flash.ps1 -Port COM7 -Chip esp32c3   # ESP32-C3 boards
```

Not sure which chip you have? Run `esptool --port COM5 chip-id` (it prints the chip type). `ESP32 Dev Module` in the Arduino IDE means a classic ESP32, not a C3. If flashing fails to connect, hold the BOOT button while it starts, or lower the speed with `-Baud 115200`.

Close the Arduino Serial Monitor before flashing or capturing. Only one program can hold a serial port.

## Configure a board

Open the board's port at **921600 baud** with line ending **Newline** (the Arduino Serial Monitor works for this), then type commands. Settings are saved in flash and survive power loss.

```
CFG GET
CFG SET node_id RX1
CFG SET room_id ROOM1
CFG SET role rx
CFG SET paired_tx_mac 1a:00:00:00:00:00
REBOOT
```

Full command and setting list: [docs/serial-protocol.md](docs/serial-protocol.md).

### Demo layout A: one transmitter, two receivers in one room

| Board | Commands |
|-------|----------|
| TX | `CFG SET node_id TX1`, `CFG SET room_id ROOM1`, `CFG SET role tx`, `REBOOT` |
| RX1 (doorway link) | `CFG SET node_id RX1`, `CFG SET room_id ROOM1`, `CFG SET role rx`, `REBOOT` |
| RX2 (interior link) | `CFG SET node_id RX2`, `CFG SET room_id ROOM1`, `CFG SET role rx`, `REBOOT` |

The default transmitter address and the default paired address are the same (`1a:00:00:00:00:00`), so nothing else is needed.

### Demo layout B: the RoomSense spec's two room links plus a tag

Each room has its own transmitter with its own address, and each receiver is paired to one of them:

| Board | Commands |
|-------|----------|
| TX1 | `CFG SET node_id TX1`, `CFG SET room_id ROOM1`, `CFG SET role tx`, `CFG SET own_mac 1a:00:00:00:00:01`, `REBOOT` |
| TX2 | `CFG SET node_id TX2`, `CFG SET room_id ROOM2`, `CFG SET role tx`, `CFG SET own_mac 1a:00:00:00:00:02`, `REBOOT` |
| RX1 | `CFG SET node_id RX1`, `CFG SET room_id ROOM1`, `CFG SET role rx`, `CFG SET paired_tx_mac 1a:00:00:00:00:01`, `CFG SET tags E1`, `REBOOT` |
| RX2 | `CFG SET node_id RX2`, `CFG SET room_id ROOM2`, `CFG SET role rx`, `CFG SET paired_tx_mac 1a:00:00:00:00:02`, `CFG SET tags E1`, `REBOOT` |
| Tag | `CFG SET node_id TAG1`, `CFG SET role tag`, `CFG SET tag_id E1`, `REBOOT` |

All boards must use the same channel (default 11; change with `CFG SET channel 1`, 6 or 11). Pick the quietest of 1, 6 and 11 at the venue.

## Read the stream and record training data

```powershell
cd firmware\tools
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -e .
.\.venv\Scripts\python.exe -m pytest                      # protocol tests
copy authorized_installers.example.txt authorized_installers.txt   # then edit it
.\.venv\Scripts\rs-capture.exe --port COM5 --port COM6 --label moving --installer alice --consent
```

`rs-capture` writes one CSV per class (`empty`, `moving`, `still_present`) under `firmware/tools/data/` (git-ignored). Recording is limited to allow-listed installers and consenting people (spec requirements 17 and 21.5). Other code should import `roomsense_hub` (`parse_line`, `format_record`) instead of writing a second parser.

## Build from source

Needs ESP-IDF v6.0 (install with Espressif's `eim`, with the `mcp` feature if you want Kiro to drive the build). The first build downloads the `esp_csi_gain_ctrl` component, so it needs internet.

```powershell
cd firmware
idf.py set-target esp32c3          # or esp32
idf.py build
```

For a C3 board that uses the chip's built-in USB instead of a USB-to-serial chip:

```powershell
idf.py -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.usbserial" set-target esp32c3
```

After changing the code, rebuild and refresh the committed images: `esptool --chip <chip> merge-bin -o prebuilt/roomsense-<chip>.bin @flash_args` from the build folder.

## Layout

| Path | What |
|------|------|
| `main/` | The firmware (config, radio, tx, rx, tag, console, protocol formatting) |
| `docs/serial-protocol.md` | The serial contract |
| `tools/` | Python reader, parser, and training-data recorder, with tests |
| `prebuilt/` | Single-file flash images for `flash.ps1` |
| `flash.ps1` | Flash helper that uses the Arduino IDE's esptool |

## Credits

CSI capture follows Espressif's [esp-csi](https://github.com/espressif/esp-csi) `csi_send` and `csi_recv` examples (Apache-2.0). Receive-gain compensation comes from Espressif's `esp_csi_gain_ctrl` component, downloaded at build time.
