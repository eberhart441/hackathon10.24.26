# Flashing plan and real-world test protocol (6x Inland ESP32-WROOM-32D)

> **Alternative approach, not the main system.** This file and the Arduino sketches in `firmware/board_check`, `firmware/espnow_gateway` and `firmware/espnow_room_node` use PIR/radar sensors over ESP-NOW. The team's main system is the WiFi-CSI firmware in `firmware/main` (see [firmware/README.md](firmware/README.md)). The sketches have not been compiled yet.

Your boards are classic ESP32 (dual-core, Wi-Fi + Bluetooth). They support ESP-NOW and Wi-Fi channel data (CSI). Pins used below are all safe on this chip.

> **Not yet compiled.** These sketches were written against the standard ESP32 Arduino core but could not be built where I wrote them. Your first flash is the real compile test. Use **core 3.x** if you have the choice (RSSI is only reported there). If a sketch fails to compile, paste the first error into Kiro or send it to me.

## 1. Flash plan

| Board | Role | Sketch | Setting to change |
|---|---|---|---|
| all 6, first | identify | `firmware/board_check` | none: note the MAC, put tape on it |
| 1 | **GW** gateway (stays plugged into the laptop) | `firmware/espnow_gateway` | none |
| 2-5 | **R1-R4** room nodes | `firmware/espnow_room_node` | `NODE_ID` = 1, 2, 3, 4 (re-flash for each board) |
| 6 | **SP** spare, then use as hallway/door node | `firmware/espnow_room_node` | `NODE_ID` = 5 |

Arduino IDE: Tools > Board > **ESP32 Dev Module**, then pick the board's COM port. If upload hangs on "Connecting....", hold **BOOT** until it starts. Close the Serial Monitor before using the dashboard or `link_test.py`: only one program can hold a COM port.

**Why this design:** ESP-NOW needs no router, no password and no internet, so the sensor network keeps working when building Wi-Fi dies. That is the point of the product. Every node broadcasts, so you never configure MAC addresses.

## 2. Wiring (per room node)

| Sensor | Pin | Notes |
|---|---|---|
| PIR (HC-SR501) OUT | GPIO 27 | VCC to VIN (5 V). Needs about 60 s warm-up after power-on, so don't judge it before that |
| LD2410 radar OUT (optional) | GPIO 26 | 5 V power. Reads LOW when absent, so leaving it unconnected is safe |
| HC-SR04 TRIG (optional) | GPIO 25 | Set `USE_ULTRASONIC 1` |
| HC-SR04 ECHO (optional) | GPIO 33 | **Through a voltage divider (1 kΩ in series, 2 kΩ to GND).** The echo pin outputs 5 V and ESP32 pins are not 5 V tolerant |

Power each node from a USB power bank. Test your actual bank (see T8): some banks switch off when the load is low.

## 3. Test ladder

Start the logger on the laptop for every link test: `python link_test.py COM5` (from `python\`, venv active). It saves every packet to `python\data\link-*.csv`. Run `python link_test.py --simulate` once first to see what the table looks like.

| # | Test | Procedure | Pass criterion | Record |
|---|---|---|---|---|
| T1 | Bench link | One node 1 m from the gateway, 5 min | Loss under 1% | loss %, RSSI |
| T2 | Range and walls | Node at: same room 3 m / next room through 1 wall / two walls or hallway / another floor. 5 min each | Loss under 5% at every spot you'll use in the demo | table of loss and RSSI per placement |
| T3 | Venue interference | Repeat T1 with `WIFI_CHANNEL` 1, 6 and 11 (change in **both** sketches and re-flash) | Pick the channel with the lowest loss | loss per channel |
| T4 | PIR response | Walk in and out 10 times | Detected within about 1-2 s every time | detection rate, delay |
| T5 | **Still person** (the important one) | Sit completely still in view of the sensor, then lie still. Watch `pir` and `sm` | **Expect PIR to fail.** Record how many seconds until `pir=0`. With LD2410: `rad` should stay 1 for 5 min at 1, 2 and 3 m | seconds to drop, radar hold time |
| T6 | False positives | Empty room for 10 min with a fan, HVAC and sunlight on the sensor | Zero false OCCUPIED, or write down the count | false triggers per 10 min |
| T7 | Failure behavior | Unplug a node; power-cycle the gateway; reset a node mid-run | The node shows **LOST** within 5 s; the gateway recovers without re-flashing nodes; a node restart shows up as a reboot | time to LOST |
| T8 | Power | Run a node on your power bank for 2 h | Still reporting at the end | runtime |
| T9 | Demo rehearsal | Run the full cardboard-building scenario 3 times, timed | Same result all 3 runs, under 3 min | times |
| T10 | Real room | In a room you have permission to use, with real doors | Works as in the model, or you know why not | notes |

## 4. How to read the results

- **PIR drops while someone sits still.** That is expected. It is exactly why the product has a LIKELY OCCUPIED state, and why the radar and door logic matter. Report the T5 number in your README as a **limitation you measured**, not a surprise.
- **A node that stops reporting is information.** It may have lost power, or the room may be burning. The dashboard shows last-known state plus its age.
- **Loss over 5%:** move the node, change the channel, or add a relay node (the spare). Don't hide the numbers.

## 5. Paste into the README after testing

```
## Measured results (hackathon day)
| Test | Result |
|---|---|
| Packet loss, same room (T1) | __ % |
| Packet loss, through 1 wall (T2) | __ % |
| Best Wi-Fi channel at venue (T3) | __ |
| PIR time-to-drop with a still person (T5) | __ s |
| Radar hold time with a still person (T5) | __ min  (or "not tested, no radar") |
| False triggers, empty room, 10 min (T6) | __ |
| Time for dashboard to flag a lost node (T7) | __ s |
```

Judges trust specific numbers and honest limits more than claims.

## 6. Safety and ethics

- **No real smoke, fire or heat near the boards or the building.** Simulate with tissue paper and the SIMULATED ALARM button. Real smoke sets off the venue's fire alarm.
- Only place sensors where you have permission, and tell people in the room they're being sensed. The system sees presence only, never identity.
- Say "decision support" in the pitch, not "life-saving."
