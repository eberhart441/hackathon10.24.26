# Serial protocol (firmware to hub)

The authoritative definition is **`.kiro/specs/beacon-occupancy-tool/design.md`**, section "Serial line formats". This page restates the parts the firmware implements and documents the setup commands, so you do not have to dig through the design. If the two ever disagree, `design.md` wins and the firmware gets fixed.

Requirements covered: 2 (CSI capture and transport), 3 (configuration, heartbeats, reboot resilience), 23 and 24 (responder tag, tag summaries).

## Who talks on the serial port

| Role | Runtime serial output | Notes |
|------|----------------------|-------|
| `rx` (RX_Node) | `CSI`, `HB`, `TAG` lines | The only role the hub reads while running |
| `tx` (TX_Node) | none | Setup commands only. The hub infers its health from its receiver's `measured_pps` |
| `tag` (Responder_Tag) | none | Setup commands only. The hub notices a dead tag by silence |

Transport is **UART at 921600 baud, 8N1**, one port per receiver. UDP and binary framing are not implemented (deferred in the design).

## Framing rules

- ASCII text, one record per line, ending in `\n` (a preceding `\r` is allowed). Fields are comma-separated and never contain commas, spaces or newlines.
- A record starts at the first character of the line with its type (`CSI,`, `HB,`, `TAG,`).
- The port also carries boot-ROM text and ESP-IDF log lines. **Readers ignore every line that is not a valid record**, and a reader that starts mid-line discards that one partial line.
- The receiver writes whole lines only. If its output queue is full it drops the whole record, which the hub sees as a gap in `seq`. It never writes a partial record.

## Records (receivers)

```
CSI,<node_id>,<tx_mac>,<seq>,<ts_us>,<rssi_dbm>,<channel>,<n_sub>,<amp_0>,<amp_1>,...,<amp_n_sub-1>
HB,<node_id>,<room_id>,<paired_tx_mac>,<fw_version>,<uptime_ms>,<measured_pps>,<free_heap>,<csi_q_drops>,<rx_mode>
TAG,<node_id>,<room_id>,<tag_id>,<packets_heard>,<mean_rssi>,<max_rssi>
```

### CSI (one per accepted packet)

| Field | Meaning |
|-------|---------|
| node_id | This receiver's name |
| tx_mac | MAC of the paired transmitter, lowercase `aa:bb:cc:dd:ee:ff`. Always the paired transmitter; no other device's address is ever printed |
| seq | Transmitter's packet counter (32-bit). Goes up by 1 per packet |
| ts_us | Receiver's local microsecond clock when the packet arrived. **32-bit; wraps about every 71.6 minutes, so readers must unwrap it** |
| rssi_dbm | Signal strength, negative integer |
| channel | WiFi channel |
| n_sub | Number of amplitudes that follow. **The firmware currently sends 64** (the L-LTF subcarriers as captured) |
| amp_i | `sqrt(I squared + Q squared)` of subcarrier i, integer 0 to 255 |

Null and guard subcarriers are included as captured (they read 0 or near 0); the hub drops them when cleaning. On some chips the first two samples are invalid and are sent as 0. Amplitudes are corrected for receiver gain changes only on chips that support it (not the classic ESP32).

A CSI line is about 330 bytes, so about 33 KB/s at 100 packets/s, which fits in 921600 baud (about 92 KB/s).

### HB (once per second, receivers only)

| Field | Meaning |
|-------|---------|
| paired_tx_mac | The one transmitter this receiver listens to (`00:00:00:00:00:00` until set) |
| fw_version | Firmware version |
| uptime_ms | Milliseconds since boot (32-bit) |
| measured_pps | CSI packets accepted from the paired transmitter in the last second. **The only transmitter-health signal** (requirement 19.7) |
| free_heap | Free heap in bytes |
| csi_q_drops | Records dropped because the output queue was full, cumulative since boot |
| rx_mode | `HUB`. (`EDGE` and `TRAINING` are not implemented yet) |

No CSI or occupancy data in heartbeats. The hub marks a receiver offline after 10 seconds without one.

### TAG (once per second per commissioned tag heard)

`packets_heard` is the number of tag broadcasts heard in the last second; `mean_rssi` is the mean with one decimal; `max_rssi` is an integer. Nothing is printed for a tag that was not heard that second. Only commissioned tag IDs (the receiver's `tags` setting) are ever reported, and a tag's MAC address is never printed. Tag packets are handled separately from CSI.

## Setup commands (all roles)

Send one command per line at 921600 baud with a newline (the Arduino Serial Monitor works with "Newline" selected). Settings are stored in flash, survive power loss, and apply after `REBOOT`. A rebooted node resumes by itself.

| Command | Reply | What it does |
|---------|-------|--------------|
| `SET key=value [key=value ...]` | `OK,SET,<key>` or `ERR,SET,<reason>` for each pair | Validate and save settings |
| `GET` | `CFG,<key>=<value>` lines | Print the saved settings, plus this board's `mac` and `fw_version` |
| `PING` | `PONG,<node_id>` | Check the node is listening |
| `REBOOT` | `OK,REBOOT` | Restart |
| `FACTORY_RESET` | `OK,FACTORY_RESET` | Erase saved settings |

The replies are an addition; `design.md` does not define any. Lines starting `CMD,` (the hub's alarm and calibration commands for edge mode) are ignored silently. Anything else gets `ERR,CMD,unknown`.

| Key | Used by | Values | Default |
|-----|---------|--------|---------|
| node_id | all | up to 15 letters, digits, `_` or `-` | `NODE` |
| room_id | all | same | `ROOM1` |
| role | all | `tx`, `rx`, `tag` (one firmware image serves all three) | `rx` |
| channel | all | `1`, `6` or `11`. **All nodes must match** | `11` |
| pps | tx, tag | packets per second, 1 to 200 | tx 100, tag 10 |
| peer | tx | MAC of the paired receiver to send to. `ff:ff:ff:ff:ff:ff` sends to every receiver | broadcast |
| paired_tx | rx | MAC of the paired transmitter. A transmitter keeps its factory MAC; read it with `GET` on the transmitter | none |
| tag_id | tag | up to 4 letters, digits, `_` or `-` | `E1` |
| tags | rx | commissioned tag IDs, comma separated, for example `E1,E2` | none |
| rx_mode | rx | `HUB` only | `HUB` |
| relay_to | rx | MAC of the master to relay data to, or `off` | `off` |
| relays | tx | receivers whose relayed data this master prints, comma separated MACs (up to 4), or `none` | `none` |

### Relay mode (optional, only the master on USB)

Off by default. With `SET relay_to=<master mac>` on each receiver and `SET relays=<rx1 mac>,<rx2 mac>` on the master (then `REBOOT` all), receivers send their `CSI`, `HB` and `TAG` lines over the air to the master, batched about 4 lines per frame at HT MCS4, and the master prints them on its USB port unchanged. The hub reads one port and sees the same lines as before. A relaying receiver prints only command replies on its own USB port. Lines the relay could not deliver are added to that receiver's `csi_q_drops`. Not yet tested on hardware; whether the extra radio traffic hurts sensing has not been measured.

`peers` (the edge-mode list of commissioned receivers) is recognised but rejected with `ERR,SET,not_implemented`.

### Pairing a transmitter and a receiver

1. On the transmitter: `GET`, and note the `mac`.
2. On the receiver: `SET paired_tx=<that mac>`, and `REBOOT`.
3. On the receiver: `GET`, note its `mac`. On the transmitter: `SET peer=<receiver mac>`, and `REBOOT`.

If you skip step 3 the transmitter broadcasts, which also works (any receiver paired to it will hear it).

## Rules for readers

1. Ignore anything that is not a valid record.
2. Unwrap `ts_us`.
3. Packet loss is gaps in `seq` for one (receiver, transmitter) stream. A `seq` that goes backwards means the transmitter restarted, not loss.
4. A receiver with no heartbeat for 10 seconds is offline. Do not treat a quiet room and a dead node as the same thing.
5. Never show or store a field the protocol does not define.

## Reference implementation

`firmware/tools/beacon_hub/protocol.py` parses and formats every record above (`parse_line`, `format_record`). Use it, or its `format_record` in the simulator, rather than writing a second parser.
