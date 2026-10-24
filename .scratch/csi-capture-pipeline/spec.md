Status: ready-for-agent

> **Revision (after the Beacon requirements spec landed).** The intent below still holds. Changes made while implementing, so the firmware meshes with `.kiro/specs/beacon-occupancy-tool`. **Where this spec and `design.md` disagree, `design.md` wins** (it defines the final line formats, for example no `room_id` in CSI lines and receiver-only heartbeats):
> - CSI records carry the transmitter MAC and the channel (spec Req 2.3). Final format: `firmware/docs/serial-protocol.md`.
> - Node and room names, role, channel, paired transmitter and commissioned tags are set over serial (`SET key=value`) and stored in flash, not chosen at build time (spec Req 3). One image serves every role.
> - Added the responder-tag role and `TAG,...` summaries (spec Req 23, 24). Only receivers send heartbeats.
> - The transmitter unicasts to its paired receiver (or broadcasts if none is set), so the spec's "2 TX + 2 RX" layout works as well as "1 TX + 2 RX".
> - `esp_csi_gain_ctrl` is downloaded at build time as an IDF managed component, not copied into the repo. UDP transport is deferred.
> - Needs ESP-IDF v6.0 (some API names changed, for example `WIFI_BW20`).
> - Glossary mapping: master = TX_Node, slave = RX_Node.

# CSI capture pipeline (master and slave firmware, serial stream, laptop ingest)

## Problem Statement

We are building a system that senses people in a room using WiFi signals, with no cameras and nothing for occupants to carry. Everything downstream (the motion model, the room state machine, the dashboard) depends on one thing working first: getting clean, aligned CSI measurements from two links to the laptop at a steady rate. Right now there is no firmware, no agreed data format, and no laptop-side reader. The ML teammate has no data to train on, the state-machine and dashboard work cannot be tested against real input, and we do not yet know whether CSI shows a clear signal when someone walks through the demo room. This is the hour-1.5 go/no-go for the whole project.

## Solution

A capture pipeline with three parts:

1. **Master firmware** on one ESP32-C3 that broadcasts a steady stream of tiny packets on a fixed channel.
2. **Slave firmware** on two ESP32-C3 boards that listen to the master only, turn each packet's CSI into a compact list of amplitudes, and print one text line per packet to their serial port, plus periodic status lines.
3. **Laptop ingest** that reads both slaves' serial ports, parses the lines, lines the two links up by the master's packet counter, counts lost packets, and writes timestamped CSV recordings that the ML teammate can label and train on.

One firmware project builds all three roles. Any board can be flashed as the master or either slave. The line format between the slaves and the laptop is the contract that everything else is built against.

## User Stories

1. As the firmware developer, I want one firmware project that builds the master and both slaves, so that any board can take any role and I can reflash a spare if one fails.
2. As the firmware developer, I want to choose a board's role and slave number when I build it, so that I never have to edit source to switch roles.
3. As the firmware developer, I want each role to build into its own output folder, so that building one role does not overwrite another.
4. As the firmware developer, I want the target chip set to ESP32-C3, so that the build matches the boards we own.
5. As the firmware developer, I want to start from Espressif's own sender and receiver examples, so that I do not reinvent CSI capture.
6. As the firmware developer, I want the needed esp-csi files copied into the repo with their license kept, so that a judge who clones the repo can build it without extra downloads.
7. As the firmware developer, I want the repo to credit Espressif for the code we reused, so that the "used vs. built" split is clear.
8. As the master, I want to broadcast a packet 100 times per second on a fixed channel, so that the slaves get a steady stream of CSI samples.
9. As the master, I want to use a fixed, known hardware address and put an incrementing counter in every packet, so that slaves can recognize me and the laptop can line up samples.
10. As the master, I want to run from a battery pack with no computer attached, so that we can demo the system after wall power is cut.
11. As the master, I want to print a short startup banner when a USB cable is attached, so that I can confirm which role and channel I booted with.
12. As a slave, I want to ignore every frame that does not come from the master, so that I never record or report other people's devices.
13. As a slave, I want to turn the first 64 CSI values of each packet into 64 amplitude numbers, so that the output is compact and consistent.
14. As a slave, I want amplitudes to stay in their original subcarrier positions, including the zero-valued guard positions, so that position in the list always means the same frequency component.
15. As a slave, I want to print exactly one text line per received packet, so that the laptop can process the stream line by line.
16. As a slave, I want to include the master's packet counter, my own slave number, my local microsecond clock, and the signal strength in every line, so that the laptop can align, order and sanity-check samples.
17. As a slave, I want to print one startup line with my slave number, firmware version, channel and bandwidth, so that logs are self-describing.
18. As a slave, I want to print a status line once per second with my uptime, packet count and channel, so that the laptop can tell I am alive even when no packets arrive.
19. As the firmware developer, I want radio settings (channel, bandwidth, packet rate, master address, serial speed) to be configuration values in one place, so that changing the venue channel is a rebuild, not a code change.
20. As the firmware developer, I want 20 MHz bandwidth and 100 packets per second as defaults, so that we start with less interference and a rate the serial link can carry.
21. As the firmware developer, I want to be able to pick the channel at the venue, so that we avoid the busiest part of the crowded 2.4 GHz band.
22. As the firmware developer, I want the serial output to work whether a board uses a USB-to-serial chip or the chip's built-in USB, so that I am not blocked by which board model we end up with.
23. As the laptop operator, I want to read two slaves at once on two serial ports, so that both links are captured together.
24. As the laptop operator, I want the ingest to stamp each line with the laptop's arrival time, so that recordings have a common clock even though the boards' clocks differ.
25. As the laptop operator, I want lines from the two slaves matched by the master's packet counter, so that each moment has one sample per link.
26. As the laptop operator, I want lost packets counted from gaps in the packet counter, so that I know how reliable each link is.
27. As the laptop operator, I want a running count of lost packets per link shown while capturing, so that I can spot a bad link immediately.
28. As the laptop operator, I want malformed, truncated or garbled lines skipped without stopping the capture, so that one corrupted line never loses a recording.
29. As the laptop operator, I want ordinary boot-log text from the chip to be ignored by the parser, so that debug output does not break parsing.
30. As the laptop operator, I want to detect when a slave has gone silent, so that I can tell a dead link from a quiet room.
31. As the laptop operator, I want to detect a master restart (the counter jumping backwards), so that I do not report a huge false burst of lost packets.
32. As the laptop operator, I want each recording saved as a CSV with arrival time, slave number, packet counter, local clock, signal strength and the 64 amplitudes, so that the ML teammate can load it directly.
33. As the laptop operator, I want to attach a label (for example empty, walking, lying still) to a recording session, so that the ML teammate gets labeled training data.
34. As the laptop operator, I want recordings to be written continuously as data arrives, so that a crash does not lose a whole session.
35. As the laptop operator, I want to choose the serial ports and speed from the command line, so that I can plug boards into different ports.
36. As the ML teammate, I want a documented line and CSV format, so that I can write my training code before the hardware is working.
37. As the ML teammate, I want a small committed sample recording captured from real hardware, so that I can develop against real numbers.
38. As the demo operator, I want to walk across a link and see a clear change in the numbers, so that we know within the first hour and a half whether CSI works in our room.
39. As the demo operator, I want to calibrate with the room empty, so that the baseline reflects the room as it will be during the demo.
40. As the demo operator, I want the master to keep transmitting when disconnected from the laptop, so that the "power cut, still working" demo works.
41. As the Kiro agent, I want a precise written contract for the line format, so that I can generate and review code on both sides without guessing.
42. As the Kiro agent, I want the build and flash steps available through the ESP-IDF tool server, so that I can build and flash without copying commands by hand.
43. As a teammate, I want setup steps written down (toolchain install, build per role, flash, capture), so that anyone on the team can reproduce a working capture.
44. As a judge, I want the repo to contain everything needed to build and run the capture pipeline, so that the project is reproducible.

## Implementation Decisions

- **Toolchain and base:** plain ESP-IDF, requiring v6.0 or newer so the built-in tool server for the dev assistant works. Firmware starts from Espressif's esp-csi sender and receiver examples. The needed esp-csi pieces (sender, receiver, gain-control component) are copied into the repo with the Apache-2.0 license and notices kept, rather than using a git submodule. The README credits Espressif.
- **Project structure:** one firmware project for all three roles. A configuration option selects role (master or slave) and slave number (1 or 2). Per-role configuration overlays and per-role build folders keep builds independent. Target chip is ESP32-C3.
- **Master behavior:** broadcast over ESP-NOW to all receivers, using the fixed locally set hardware address from the example, at 100 packets per second, on a fixed channel, 20 MHz bandwidth, lowest MCS rate. The payload is a 32-bit counter that increments per packet. The master needs only power.
- **Slave behavior:** run in promiscuous mode with the CSI callback. The first action in the callback is to discard any frame whose source address is not the master's. Read the master's counter from the payload. Convert the first 64 CSI values (I/Q pairs) into 64 unsigned 8-bit amplitudes using the magnitude of each pair, keeping guard positions in place. Emit one line per packet.
- **Gain compensation:** use the gain-control component from esp-csi as provided for the C3 target.
- **Line contract (text, one record per line, comma-separated, newline-terminated):**
  - A startup record carrying: record type, slave number, firmware version, channel, bandwidth.
  - A per-packet CSI record carrying: record type, slave number, master counter, slave-local microsecond timestamp, signal strength in dBm, then the 64 amplitudes in subcarrier order.
  - A once-per-second status record carrying: record type, slave number, uptime in milliseconds, count of packets accepted from the master, current channel.
  - Anything else on the serial port (boot logs, warnings) is not part of the contract and must be ignored by readers.
- **Data rate:** about 250 to 300 bytes per CSI record by estimate, so roughly 25 to 30 KB/s per slave. Standard UART-bridge boards need at least 460800 baud. Native-USB boards are not baud-limited. Move to a binary framing only if this proves insufficient.
- **Configuration values (one place):** channel, bandwidth, packet rate, master address, serial speed, role, slave number, firmware version string. Changing the channel means rebuilding and reflashing all three boards; a runtime channel command is deferred.
- **Serial console:** configurable to match the board type (USB-to-serial chip or built-in USB). The board model is not yet known, so both must remain supported.
- **Laptop ingest module (Python):**
  - Opens one serial port per slave and reads lines continuously.
  - Parses the three record types according to the line contract; skips anything malformed or unrelated without raising.
  - Stamps each record with laptop arrival time.
  - Aligns the two slaves by the master's counter, tolerating missing samples on either side.
  - Counts lost packets per link from counter gaps; treats a backward jump in the counter as a master restart, not as loss.
  - Marks a link silent after a configurable period with no records (status records count as proof of life).
  - Writes a CSV per session, appending continuously, with columns for arrival time, slave number, counter, local clock, signal strength and the 64 amplitudes; the session carries a free-text label.
  - Command line options for serial ports, speed, label, and output location.
- **Privacy posture for this feature:** only the master's frames are processed, and no other device's address is parsed, stored or printed. Extra enforcement (tests or hooks) is deprioritized by team decision and out of scope here. Raw CSI is streamed to the laptop over a wired USB connection; it is not sent over a network and is not stored beyond the labeled recordings of consenting teammates used for training.
- **Development tooling:** the ESP-IDF built-in tool server (build, flash, clean, set target, list ports) is the primary assistant integration. Optional: a community serial-monitor tool server for single-board bring-up (not suitable for two live slaves). A custom tool server for recording labeled CSI from both slaves is planned but is a separate piece of work.
- **Terminology:** master, slave, link, node, CSI, doorway link, interior link as defined in the project glossary.

## Testing Decisions

- **What makes a good test:** only external behavior at the line contract, never internal implementation details. A test should say "given these lines, the reader reports this", not "this helper function was called".
- **Single seam:** the serial line protocol. Tests feed lines (as a stream of text) into the Python ingest and check what comes out: parsed records, alignment between links, lost-packet counts, silent-link detection, and CSV contents.
- **Property-based tests (Hypothesis):**
  - Valid records of each type, generated from the contract, always parse back to the same values.
  - Arbitrary garbage, truncated lines, and interleaved boot-log text never crash the reader and never produce a bogus record.
  - Lost-packet counts equal the number of missing counter values for any sequence with gaps, and a backward jump is reported as a restart, not loss.
  - Alignment by counter yields at most one sample per link per counter value and never pairs different counters.
  - Amplitudes always stay in the 0 to 255 range and there are always exactly 64 per CSI record.
- **Golden fixture:** a short real capture from the hardware (with real boot-log noise in it) is committed and must parse cleanly. This is how the firmware is checked against the contract without needing hardware in the automated tests.
- **Not automated:** whether CSI shows a clear signal when someone crosses the link is a manual bring-up check on the real hardware (the go/no-go). Firmware behavior on the board is verified by flashing and inspecting output.
- **Prior art:** none yet; the repo currently contains only documents. These tests establish the pattern for the later specs (model wrapper, state machine, dashboard).

## Out of Scope

- The motion/no-motion model and its training.
- Self-calibration, the room state machine, lost-trail flagging, and the dashboard.
- The simulator.
- The alarm trigger and incident mode.
- On-node motion scoring (an optional stretch, decided after streaming works).
- Enforcement of privacy rules through tests or hooks (deprioritized for now).
- Binary serial framing, runtime channel changes, and over-the-air updates.
- A custom MCP server for recording labeled CSI (planned, tracked separately).
- Multi-room or multi-building layouts.

## Further Notes

- **Open items:** the exact ESP32-C3 board model and its USB type are not yet known; the ML teammate has not yet confirmed that 64 amplitudes per packet is enough for the model; the venue channel can only be chosen on site.
- **Prerequisite:** ESP-IDF v6.0 or newer installed with Espressif's installer (v0.8.1 or newer) with its `mcp` feature enabled, so the built-in tool server is available to Kiro.
- **Go/no-go:** if no clear signal is visible when walking across a link by about the 1.5-hour mark, switch to the fallback sensing plan in the project context.
- **Hardware matching:** extra boards should be the same ESP32-C3 model so all nodes behave alike and CSI sizes stay consistent.
- **Mixed-up roles:** because any board can be any role, label each board physically (master, slave 1, slave 2) after flashing.
- This spec's design details come from the firmware design section of the project context file; if the two disagree, update both.
