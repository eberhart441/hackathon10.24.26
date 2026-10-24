# Serial Protocol v1 (firmware to hub)

This is the contract between the node firmware and everything that reads it: the data pipeline, the detection model, the dashboard, the simulator and the capture tool. Build against this document, not against the firmware source.

It implements the firmware-facing parts of the RoomSense requirements (`.kiro/specs/roomsense-occupancy-tool/requirements.md`): Requirement 2 (CSI capture and transport), 3 (configuration and heartbeats), 19 (health), 23 and 24 (responder tag and tag summaries).

## Terms

| This document / glossary | RoomSense spec |
|--------------------------|----------------|
| master | TX_Node |
| slave | RX_Node |
| tag | Responder_Tag |
| link | one TX_Node paired with one RX_Node |

A **room** can have more than one link. Two receivers can report the same `room_id` (for example a doorway link and an interior link in one conference room), or each receiver can have its own room. Firmware does not care; the hub decides how links map to rooms.

## Transport

- **UART, 921600 baud, 8N1** by default. UART is the primary transport (Req 2.4). A board that uses the chip's built-in USB serial has no baud rate to set.
- UDP (Req 2.5) is **not implemented** in this version.
- One text stream per node. Each node is its own serial port.

## Framing rules

- UTF-8 text. One record per line, ending in `\n` (a preceding `\r` is allowed).
- Fields are comma-separated. No field ever contains a comma, a space, or a newline.
- A protocol line starts at the first character of the line with its record type, such as `CSI,`.
- **Readers must ignore every line that is not a valid record.** The serial port also carries boot-ROM text and ESP-IDF log lines. A reader that starts in the middle of a line will see one partial line first; discard it.
- A record is valid only if it has exactly the number of fields listed below and every field is in range.
- Every record is produced by a single write, so lines from one node are never interleaved with each other.

## Records sent by the firmware

### BOOT: sent once at startup

```
BOOT,<node_id>,<role>,<room_id>,<fw_version>,<channel>,<bandwidth>
```

| Field | Type | Meaning |
|-------|------|---------|
| node_id | text | Commissioned node name, for example `RX1` |
| role | `tx`, `rx` or `tag` | What this board does |
| room_id | text | Room this node is assigned to |
| fw_version | text | Firmware version |
| channel | integer | WiFi channel in use (1, 6 or 11) |
| bandwidth | text | `HT20` |

### HB: heartbeat, once per second (Req 3.1, 19)

```
HB,<node_id>,<role>,<room_id>,<uptime_ms>,<pps>,<channel>,<dropped>
```

| Field | Type | Meaning |
|-------|------|---------|
| uptime_ms | integer | Milliseconds since boot (32-bit, wraps after about 49 days) |
| pps | integer | Measured packet rate over the last second. For `tx`: packets sent. For `rx`: CSI packets accepted from the paired transmitter. For `tag`: broadcasts sent |
| channel | integer | Channel in use |
| dropped | integer | Records the node had to drop because its output queue was full (cumulative since boot) |

Heartbeats never contain CSI or occupancy data (Req 19.2). The hub treats a node as offline when it has seen no heartbeat for 10 seconds. A receiver that is alive but reports a very low `pps` points at a dead transmitter (Req 19.7). A transmitter that is battery powered with no USB cable has no way to send heartbeats to the hub, so its health is inferred from the receiver's `pps`.

### CSI: one per accepted packet (Req 2.3), receivers only

```
CSI,<node_id>,<room_id>,<tx_mac>,<seq>,<t_us>,<rssi>,<channel>,<n>,<a0>,<a1>,...,<a(n-1)>
```

| Field | Type | Meaning |
|-------|------|---------|
| tx_mac | `aa:bb:cc:dd:ee:ff` | MAC address of the paired transmitter (lowercase hex). Always the paired transmitter; no other device's address is ever output |
| seq | integer 0 to 4294967295 | Transmitter's packet counter. Increments by 1 per packet |
| t_us | integer 0 to 4294967295 | Receiver's local microsecond clock when the packet arrived. **A 32-bit counter that wraps about every 71.6 minutes; readers must unwrap it** |
| rssi | integer, dBm | Signal strength of the packet (negative) |
| channel | integer | Channel the packet was received on |
| n | integer | Number of amplitudes that follow. **Currently always 64** |
| a0..a(n-1) | integer 0 to 255 | Amplitude of each subcarrier, `sqrt(I squared + Q squared)` of the CSI sample |

Notes on the amplitudes:
- They come from the first 64 CSI samples of the packet (the legacy training field).
- Subcarrier positions are preserved, including the guard and null subcarriers, which read as 0 or near 0. The pipeline drops them (Req 4.3). Position in the list always means the same frequency component.
- On some chips the first two samples can be invalid; the firmware sets those to 0.
- Amplitudes are corrected for receiver gain changes where the chip supports it, and clipped to 255.
- Size is roughly 280 bytes per record, about 28 KB/s at 100 packets/s.

### TAG: tag summary, once per second per tag heard (Req 24.4)

```
TAG,<node_id>,<room_id>,<tag_id>,<packets_heard>,<mean_rssi>,<max_rssi>
```

| Field | Type | Meaning |
|-------|------|---------|
| tag_id | text, up to 7 characters | Commissioned tag ID, for example `E1` |
| packets_heard | integer | Tag packets heard in the last second |
| mean_rssi | decimal with one digit, dBm | Mean signal strength of those packets |
| max_rssi | integer, dBm | Strongest of those packets |

Emitted only for commissioned tags, and only for seconds in which the tag was heard (Req 24.5). Receivers never output a tag's MAC address. The hub drops these in IDLE state (Req 29).

## Commands sent to the firmware

One command per line, ASCII, fields separated by single spaces.

| Command | Reply | What it does |
|---------|-------|--------------|
| `PING` | `PONG,<node_id>` | Check the node is listening |
| `CFG GET` | `CFG,<key>=<value>,...` | Print the current settings |
| `CFG SET <key> <value>` | `OK,CFG,<key>` or `ERR,CFG,<reason>` | Change and save one setting |
| `CFG RESET` | `OK,CFG,RESET` | Restore defaults and save |
| `REBOOT` | `OK,REBOOT` | Restart the node (settings apply after a restart) |

Any other command gets `ERR,CMD,unknown`.

Settings are stored in the board's flash. They survive power loss, so a node resumes streaming by itself after a reboot (Req 3.3, 3.4), and **node and room names can be changed without reflashing** (Req 3.2).

| Key | Applies to | Values | Default |
|-----|-----------|--------|---------|
| node_id | all | up to 15 characters of letters, digits, `_` or `-` | `NODE` |
| room_id | all | same | `ROOM1` |
| role | all | `tx`, `rx`, `tag` | `rx` |
| channel | all | `1`, `6`, `11` (all nodes must match) | `11` |
| pps | tx, tag | packets per second, 1 to 200 (tx default 100, tag default 10) | 100 |
| own_mac | tx | locally administered unicast MAC to transmit from (first byte like `1a`) | `1a:00:00:00:00:00` |
| paired_tx_mac | rx | the one transmitter this receiver listens to | `1a:00:00:00:00:00` |
| tag_id | tag | up to 7 characters | `E1` |
| tags | rx | commissioned tag IDs separated by `\|`, for example `E1\|E2` | empty |

Example setup for a receiver:

```
CFG SET node_id RX1
CFG SET room_id ROOM1
CFG SET role rx
CFG SET paired_tx_mac 1a:00:00:00:00:00
REBOOT
```

## Rules for readers

1. Ignore anything that is not a valid record.
2. Unwrap `t_us` (32-bit, about 71.6 minutes).
3. Packet loss is gaps in `seq` for one (node, transmitter) stream. A `seq` that goes backwards means the transmitter restarted, not that packets were lost.
4. A node with no heartbeat for 10 seconds is offline. Do not treat a quiet room and a dead node as the same thing.
5. Never show or store a field the protocol does not define.

## Reference implementation

The Python module in `firmware/tools/roomsense_hub/protocol.py` parses and formats every record above. Use it (or its `format_record` function in the simulator) rather than writing a second parser.
