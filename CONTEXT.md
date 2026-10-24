# Hackachusetts — Project Context

> Living context doc for our hackathon entry. This is the single source of truth that the team and every AI agent read first. Keep it current.

## ⚠️ PIVOT NOTICE — read this first

We have dropped the earlier plan. Older versions of this file described a health wearable (heart rate / SpO2 / IMU on an ESP32) for the Healthcare & Biotech track. **That project is cancelled.** Ignore any leftover references to wearables, vitals, MAX30102/AD8232 sensors, HIPAA framing, or the healthcare themes.

**The new project:** a WiFi-sensing system that finds people inside a building during a fire, through smoke and in rooms cameras can't see, and shows firefighters where to search first.
**The new track:** Civic Action, theme **V2: "Responsive and resilient communities"**. The theme's tagline ("Volume hides who is waiting, and who an alert misses") is close to our problem statement: the fire alarm went off, and the system shows who didn't make it out.

**What is still valid from before:** the hackathon rules, the Kiro requirements, the judging criteria, the repo setup, and the hardware we have on hand (ESP32s, Raspberry Pi, touchscreen, sensor kit).

## Event

- **Hackathon:** Hackachusetts (robotics/hardware-focused)
- **Track:** Civic Action → theme V2, Responsive and resilient communities
- **Time available:** about 8 hours of build time <!-- TODO: confirm exact start/end -->
- **Repo:** https://github.com/eberhart441/hackathon10.24.26 (public, folder `hackachusetts`)
- **Submission deadline:** <!-- TODO: exact date/time + timezone -->
- **Prizes:** 1st $3,500, 2nd $1,000, 3rd $500, split across the team. The rules' prize table calls this category "Civic Services" while the submission requirements say "Civic Action"; same amounts as every other track. Bonus prizes apply to all tracks: **Best Use of Kiro** (1-year Kiro Pro Max, ~$1,200) and **Top 50 Finalists** (WHOOP strap). One overall prize plus up to two bonus prizes per project.

## The Problem

When a building's fire alarm goes off, most people walk out. Firefighters then have to search room by room for whoever didn't, often in heavy smoke with no visibility, and they don't know which rooms to search first.

The people most likely to still be inside are those who **cannot signal for help**: people who are asleep, unconscious, injured, mobility-impaired, or hiding (children often hide during fires). They won't press a button, call out, or carry a wearable.

Existing tools fall short:

- **Cameras** are blinded by smoke, and they are banned or unacceptable in restrooms, bedrooms, and similar private spaces.
- **Wearables or phones** only work for people who carry them and keep them powered.
- **Manual searches** are slow and dangerous, and in large buildings, the order rooms get searched in is largely guesswork.

## The Solution

**One-liner:** A network of cheap ESP32 nodes that uses WiFi signal disturbances to detect human movement through smoke and walls, turns on when the fire alarm triggers, follows people room by room, and flags any room where someone's movement stopped, so firefighters search those rooms first.

**How it works:**

1. **The alarm triggers the system.** It connects to the fire alarm panel's relay output; in the demo, a button stands in for the relay.
2. **The nodes sense movement.** Human bodies disturb WiFi signals between nodes. We measure this using CSI (Channel State Information). It works in darkness and smoke and passes through drywall. No cameras, no microphones, and nothing for occupants to carry.
3. **The system follows people room by room.** It records movement between rooms and detects doorway crossings.
4. **It flags lost trails.** If someone entered a room and was active, then stopped moving and was never detected leaving, the room is flagged: *"Room 214: motion stopped 3 min ago, no exit detected → search first."* This catches people who collapsed, passed out, or are trapped.
5. **Firefighters see it on a dashboard.** The department's own floor plan, with live room states, movement trails over time, and a priority list of rooms to search.

**Who benefits:** incident commanders and search crews (faster, safer searches), building occupants who can't help themselves, and building operators in dorms, hotels, hospitals, offices, and transit stations.

**Why it scales:** each node is roughly a $10 ESP32. It needs no cameras and no changes to the building's WiFi, and it connects to standard alarm panel relays.

## Honest Capabilities & Limits (agents: do not overclaim)

| Capability | Status |
|------------|--------|
| Detecting moving people per room | ✅ Reliable. The core of the demo. |
| Detecting doorway crossings (entered/left a room) | ✅ Feasible with a link placed across each doorway |
| Inferring a still person (moved, stopped, never left) | ✅ Feasible through trail logic. **This is the key feature.** |
| Directly detecting a still body (breathing) | ⚠️ Shown in research under controlled conditions; unreliable on ESP32. Stretch goal only, labeled "experimental" if shown at all. |
| Identifying who someone is | ❌ Not possible, and deliberately so. We detect people; we never identify them. Say "detect," never "identify." |
| Precise (meter-level) position | ❌ Room/zone level only |

**Framing rule:** the system tells crews which rooms to search first. It **never clears a room**. "No motion detected" ≠ "room is empty." Every pitch, UI label, and doc must respect this.

**Known design tradeoff:** if sensing only starts when the alarm goes off, someone who collapsed *before* the alarm never registers motion. Option: run continuously in a low-detail mode that keeps only a rolling "last motion seen" time per room (no logs, no history), and switch to full incident mode on alarm. <!-- TODO: team to decide; state the choice in the pitch -->

## Privacy Rules (hard constraints — enforce in code, tests, and hooks)

1. **Raw CSI never leaves a sensor node.** Nodes send only processed motion scores.
2. **No MAC addresses, device identifiers, or phone sniffing.** Ever.
3. **Room-level detail at most.** No positions within a room, and especially none inside restroom stalls.
4. **No identity of any kind.**
5. **Incident data (trails, logs) is stored only while an incident is open.** Outside an incident, the system stores nothing beyond the low-detail mode above (if used).
6. **Demo video and repo use only consenting teammates**, filmed in a mock room, never a real restroom.

## Architecture

```
[ESP32 sensor nodes] --ESP-NOW--> [ESP32 gateway] --USB serial--> [Raspberry Pi: processing + server] --WebSocket--> [Web dashboard]
                                                                          ^
                                                          [Alarm trigger: GPIO button/relay]
```

### 1. Sensor nodes — ESP32-S3 (avoid ESP32-S2: no CSI support in esp-csi)
<!-- NOTE: Espressif's esp-csi README lists ESP32-S2 among the supported chips. S3 is still a fine choice; verify before buying or discarding boards. -->

- Firmware in C (ESP-IDF or Arduino) built on Espressif's open-source **esp-csi**.
- Nodes communicate over **ESP-NOW** (the ESP32's own peer-to-peer radio), so the system keeps working if the building's WiFi or power fails. The same packets serve for both sensing and communication.
- On-node processing: raw CSI is reduced to a per-link **motion score** (amplitude variance over a window, with outlier filtering). Packets contain `{node_id, link_id, timestamp, motion_score}`.
- **Layout rule:** at least one link crosses each doorway (acting as a tripwire for entering/leaving) and at least one covers each room's interior.
- At least one node on battery to demo "wall power cut, still reporting."

### 2. Gateway — one ESP32 on USB to the Pi

Receives ESP-NOW packets from all nodes and forwards them over serial.

### 3. Alarm trigger — Raspberry Pi GPIO

A button stands in for the fire alarm panel's relay output. A real deployment would wire into the panel's existing relay.

### 4. Processing + server — Python on the Raspberry Pi

- **Ingest:** serial reader → packet parser.
- **Zone fusion:** per-link scores → per-room activity.
- **Self-calibration:** learns each link's empty-room baseline and keeps updating it so the system stays accurate when the environment changes (doors open, furniture moved). This is our main technical depth piece. Demo it side by side against a naive fixed threshold.
- **Room state machine:** `EMPTY → ACTIVE → STILL → (EXITED via doorway crossing)`.
- **Flag rule:** entered room Z → was ACTIVE → no doorway exit → no motion for T seconds → **FLAG Z** with "still for X min."
- **Trails:** room-to-room transitions over time (room level only).
- **Storage:** SQLite incident log, written **only during an open incident**.
- **Server:** FastAPI + WebSocket push to the dashboard.

### 5. Dashboard — web app (Pi touchscreen or any laptop)

- **Floor plans:** fire departments keep pre-incident plans, usually as PDFs or images. Hackathon version: upload a floor-plan image, then draw room outlines and place nodes in a simple editor. Render with **Leaflet using `CRS.Simple`** (overlays data on a plain image). Production: import the building formats departments already use.
- **Incident view:** rooms colored by state, flagged rooms pulsing, and a **priority search list** ranked by how long each person has been still.
- **Timeline scrubber:** replay movement trails to see where people went and where a trail stopped.
- **UI language:** "Search priority," "Motion last seen." Never "Clear" or "Empty, confirmed."

### 6. Simulator + tests

- **Simulator:** generates fake node packets for a whole building (people walking, exiting, collapsing). It drives the full stack without hardware, so dashboard and logic work don't wait on firmware.
- **Property-based tests** (Python, Hypothesis) on pure logic, for example:
  - A room never becomes EXITED without a doorway-crossing event.
  - Trails are continuous: no jumps between rooms that aren't adjacent.
  - Packet encode/decode round-trips correctly.
  - Outbound data never contains anything finer than room level, or any identifier field.
  - The system holds no stored incident data when no incident is open.

## Hackathon Build (decided demo setup — overrides the Architecture and Hardware sections where they differ)

The Architecture section above is the production vision. For the 8-hour demo we are building this smaller version:

- **3 ESP32 boards:** one **transmitter** that broadcasts at a steady packet rate, and **two receivers** that pick up those packets and produce CSI. Each receiver connects to the laptop by USB serial. <!-- TODO: confirm all 3 boards support CSI (ESP32 classic and S3 do) -->
- **Laptop replaces the Raspberry Pi and touchscreen** for processing, server, and dashboard. The alarm trigger is a button on the dashboard (or a key press) instead of a Pi GPIO button.
- **Two links** (transmitter -> receiver 1, transmitter -> receiver 2): one placed across the **doorway** (entry/exit tripwire), one covering the **room interior**.
- **Demo room:** the team's small conference room with a single entrance. Measured floor plan: **13 ft x 9 ft 4 in** (about 3.96 m x 2.84 m, roughly 121 sq ft / 11.3 m², diagonal about 16 ft / 4.9 m). It is described as "square" but is actually a rectangle (about 1.4 : 1); draw the floor plan to these dimensions. The single door is **3 ft wide**, located **in a corner of the 9 ft 4 in (short) wall**. Ceiling height is not needed (CSI is mostly horizontal); what matters is node mounting height (see layout below). <!-- TODO: where the table/furniture sits, door swing direction, wall material -->
- **What the data is:** CSI is amplitude (and phase) per subcarrier over time, per link. It is **not** a 3D position. With one transmitter and two receivers we get motion per link and zone-level inference (doorway, interior), not x/y/z coordinates. "Position over time" in the dashboard means **zone / room state over time**.
- **Dashboard (floor plans + position over time):** we build it ourselves during the hackathon, vibe-coded and deliberately simple. It uses floor plans the team already drew, and shows people entering and leaving a room and the room's current state. There is no dependency on any outside software.
- **Hybrid demo:** the real room is live. Any other rooms on the floor plan are simulated by the simulator and must be **visibly labeled "SIMULATED"** on screen.

**Zone logic for one room with one entrance:** a person entering shows doorway-link activity, then interior activity. Interior activity then doorway activity, then quiet, means they left. Interior activity that stops with no later doorway event means **FLAG: motion stopped, no exit detected -> search first.** Direction (in vs out) is inferred from the order of events across the two links, not sensed directly.

**Starting node layout for this room (a first guess to validate at the hour-1.5 CSI check, not a tested design).** Call the door wall (9 ft 4 in) the "entry wall".
- **Transmitter (TX):** on a long wall, about 2 ft in from the entry wall.
- **Receiver 1 (doorway link):** on the opposite long wall, also about 2 ft from the entry wall. The TX -> RX1 line runs across the entry strip (about 9 ft 4 in), so anyone coming through the corner door has to cross it.
- **Receiver 2 (interior link):** near the far corner on the opposite short wall. The TX -> RX2 line runs diagonally through the room (about 14 ft).
- **Mounting:** put nodes on the wall or a shelf, out of the walking path so nobody bumps them. Chest height (about 3 to 4 ft) catches a standing person; a link nearer the floor (about 1 to 2 ft) is better for someone lying down. Try both during calibration.
- Keep the doorway and interior links as separate lines, and keep antennas clear of metal, the table, and the whiteboard where possible.

**Decisions and open questions for this setup**
- Receivers should compute the motion score **on the ESP32** and send only scores to the laptop, to keep Privacy Rule 1 (raw CSI never leaves a node). Raw CSI streaming stays a dev-only debug mode. <!-- TODO: team to confirm; if the laptop gets raw CSI, change Privacy Rule 1 to say so honestly -->
- Transmit with **ESP-NOW broadcast on a fixed channel** (no router or hotspot needed), using an OFDM/HT rate so CSI is produced. Start from Espressif's esp-csi send/receive examples. Pick the least busy 2.4 GHz channel at the venue.
- Receivers talk to the laptop over **USB serial**, not WiFi, so reporting doesn't use the radio that is sensing.
- Put the transmitter on a battery pack to demo "wall power cut, still working".
- **Calibrate in the real room at the venue with the room empty.** People, chairs, or doors moving during calibration or the demo will shift the baseline.

## Decisions Log (from grilling, round 1)

**Decided**
- **Dashboard:** built by us, vibe-coded, simple UI, using our own floor plans. Tracks entering/leaving events and room state.
- **ML model output:** per link, per short window, **motion / no motion** only. The simple variance threshold stays as the baseline and we show both.
- **Smoke/darkness claim:** we may claim WiFi sensing is not blocked by smoke or darkness and explain the physics in the pitch. We do not claim to have tested in a fire, never fake smoke on video, and never trigger a real alarm.
- **Accuracy:** we will run accuracy trials and report the real numbers, including any false flags.
- **Team size:** 4 (the maximum).
- **Regulatory/certification:** out of scope for the pitch (team decision).

**Still open** (not yet answered)
- Always-on minimal "motion last seen" mode vs. alarm-triggered only (see the design tradeoff above).
- Stillness timer value for the demo vs. the 3-minute figure in the pitch.
- Who owns what across the four people.
- How raw CSI reaching the laptop squares with Privacy Rule 1, and how training recordings are handled.
- Whether the dashboard shows a headcount or only events and room state.
- Whether other rooms on the floor plan are simulated and labeled.
- Phone PWA dashboard (plan: `.scratch/pwa-dashboard/plan.md`). Conflicts with the spec's "laptop screen only" and "hub binds to localhost" decisions; needs HTTPS on the hotspot, token pairing, and a spec amendment (see plan section 0, D1–D5). Decided so far: the demo phone is an **iPhone** (mkcert root CA trusted on the phone); floor plans are **hand-written JSON** in `hub/config/floorplan.json`, served by the hub at `/api/floorplan`; End incident stays on the laptop.

## Hardware

**Have:** several ESP32 boards, a Raspberry Pi, a touchscreen, breadboards/jumpers, and a sensor kit.

<!-- TODO: confirm how many ESP32s and which variants (need S3 or original ESP32, not S2). Buy 2–3 ESP32-S3 dev boards if short. -->

**Need:** a battery pack for one node, plus tape/cardboard for a mock floor plan and an "obstruction" (a sheet or cardboard wall) to show detection without line of sight.

**Fallback if CSI fails:** if nodes aren't streaming CSI and showing clear motion spikes by ~hour 1.5, switch the sensing layer to simple presence sensors from the kit (PIR, ultrasonic, door reed switches) plus the simulator. The pitch, state machine, dashboard, tests, and Kiro work stay the same.

## Data

- **Track dataset (V2):** Boston 311 service requests, provided by the hackathon. It has topic, department, status, neighborhood, and ZIP, with street addresses deliberately removed. Its link to fire evacuation is indirect. Possible uses: neighborhood-level context for where to pilot deployments. <!-- TODO: inspect the V2 zip for anything more relevant (building, safety, or emergency data) -->
- **Optional:** public WiFi CSI datasets (e.g. UT-HAR, Widar3.0) for validation, and/or publishing our own labeled ESP32 CSI dataset in the repo. The Quality & Design criteria explicitly reward public datasets.

## What We Used vs. What We Built (keep this in the README)

**Used (open source):** esp-csi (raw CSI capture), ESP-IDF/Arduino, FastAPI, Leaflet, Hypothesis.

**Built (ours):** link layout and zone fusion, self-calibration, the room state machine and lost-trail flagging, the ESP-NOW node network, the alarm trigger integration, the floor-plan editor and incident dashboard, the simulator, privacy enforcement (tests + hook), and the labeled dataset.

The rules allow open source only if we build our own functionality on top of it and comply with its license. This section makes that visible to judges.

## Submission Requirements (checklist — unchanged rules)

- [ ] Team of **max 4**, all on the submission form. One Representative submits.
- [ ] **Must use Kiro to build the project.** Thin Kiro usage = disqualification risk.
- [ ] Submit to **Civic Action**.
- [ ] Text description of features and functionality.
- [ ] **Demo video under 3 minutes**: shows the system working on the actual hardware; public on YouTube/Vimeo/Facebook Video/Youku; no copyrighted music, logos, or trademarks; no identifiable non-consenting people.
- [ ] **Public GitHub repo** with all code and assets plus instructions: firmware, Pi software, dashboard, wiring/node layout diagram, BOM, build/flash/run steps.
- [ ] **`/.kiro` directory at the repo root.** Never in `.gitignore`.
- [ ] Write-up on how Kiro was used.
- [ ] Everything in English. Original work.

Judges may score from the video, description, and images alone. **The video is the main thing they see.**

## Judging Criteria (plan the pitch and demo around these)

1. **Potential Value:** a real, clearly defined problem; who benefits; how it scales beyond the hackathon; accessibility and equity (this system specifically helps people who can't help themselves).
2. **Implementation:** how well and how deeply we used Kiro. Variety of Kiro tools, depth of understanding, strategic decisions.
3. **Quality & Design:** originality, polish, surprising combinations of technologies, intuitive UI, public resources like datasets.

**Best Use of Kiro** bonus = highest Implementation score among the top 10% of projects.

## Kiro Plan & Usage Log

| Kiro feature | Our plan | Done? |
|--------------|----------|-------|
| Tools (IDE / CLI / Web / Crew) | At least two. E.g. CLI for firmware/build scripts, IDE for specs/hooks/dashboard. Note how they differed. | [ ] |
| Spec-driven development | Requirements → design → tasks for the room state machine and flag logic, with the privacy rules written in as formal requirements. Keep a short "spec vs. vibe coding" comparison note. | [ ] |
| Agent hooks | **Privacy hook:** on save/commit, reject any change that adds MAC addresses, raw CSI, identifiers, or finer-than-room detail to outbound data. Also: run host tests on save. | [ ] |
| Steering docs | Privacy rules, the "never clear a room" framing, node pin assignments/hardware constraints, code style. | [ ] |
| MCP | Serial monitor MCP so Kiro can read the live CSI/motion stream and help tune thresholds against real data. Possibly GitHub MCP. | [ ] |
| Property-based testing | Hypothesis tests on the state machine, trails, packets, and privacy invariants (see Architecture §6). Written in parallel with the hardware build. | [ ] |
| Powers | Check what's installable; use any that fit. | [ ] |

Running notes (add dated bullets as things happen):

- <!-- e.g. "Sat 11:10 - spec generated the state-machine task list; PBT caught an EXITED-without-door bug" -->

**Repo hygiene:** the Git repo root is `hackachusetts`, with `.kiro/` directly inside it. Open Kiro with `hackachusetts` as the workspace (not `Documents`) so specs, steering, and hooks land in the right `.kiro/`. The steering file `.kiro/steering/project.md` must be rewritten for this pivot; it still describes the wearable. *(Done: rewritten with the pivot.)*

## Team

<!-- TODO: names + owners. Team size: 4 (max allowed). Known so far: one person on firmware, one buying ESP32s, one building the ML model. -->

| Name | Role | Owns |
|------|------|------|
|  | Firmware / nodes | esp-csi, ESP-NOW, on-node motion score, node layout |
|  | Processing / logic | Zone fusion, self-calibration, state machine, flag rule |
|  | Dashboard | Floor-plan editor, incident view, timeline, WebSocket client |
|  | Simulator / tests / Kiro | Simulator, Hypothesis PBT, hooks, Kiro write-up |

## Milestones (~8 hours)

- [ ] **M1 (0–1.5h):** ESP32s flashed, CSI streaming to the Pi, clear motion spike when someone crosses a link. **Go/no-go checkpoint for CSI** (see fallback).
- [ ] **M1-parallel:** simulator producing fake packets; dashboard skeleton showing the floor plan; spec + steering written; first PBT tests.
- [ ] **M2 (1.5–3.5h):** per-room motion from real nodes; doorway links detecting crossings; self-calibration working.
- [ ] **M3 (3.5–5h):** state machine + lost-trail flagging end to end; alarm button switches the system into incident mode.
- [ ] **M4 (5–6.5h):** dashboard incident view live from real hardware + simulated rooms; priority list; timeline replay; battery node demo; obstruction demo.
- [ ] **M5 (6.5–8h):** record the demo video with a time buffer, README (incl. "used vs. built"), Kiro write-up, push `/.kiro`, submit.

## Demo Video Script (draft)

1. **Problem (≈20s):** smoke blinds cameras; the people left inside are the ones who can't call for help.
2. **Alarm button pressed** → dashboard switches to incident mode.
3. **Teammate walks between taped "rooms"** → movement shows on the floor plan, behind a sheet/cardboard wall.
4. **Teammate walks into a room and lies still** → room flags as "motion stopped, no exit → search first."
5. **Wall power cut on a node** → it keeps reporting.
6. **Self-calibration vs. naive-threshold comparison.**
7. **Privacy (≈15s):** no cameras, no identities, room level only, data only during incidents.
8. **Scale (≈15s):** cost per node, alarm panel integration, buildings that benefit.

## Risks

- **CSI reliability:** sensitive to the environment. Calibrate at the venue, not at home. Hard go/no-go at hour 1.5.
- **Overclaiming:** never claim still-body detection, identification, or room clearing.
- **Phone hotspot / packet rate issues:** ESP-NOW between our own nodes avoids depending on outside WiFi.
- **Time:** get the sensing → state → dashboard loop working before polishing anything.
- **Disqualification risks:** missing `/.kiro`, `.kiro` in `.gitignore`, thin Kiro usage, video over 3:00, copyrighted music/logos, repo without run instructions.
- **Video privacy:** consenting teammates only, mock rooms only.
- **Privacy rule vs. dev workflow:** Privacy Rule 1 says raw CSI never leaves a node, but M1 and the serial-monitor MCP plan involve streaming CSI to the Pi/Kiro for tuning. Treat that as a dev-only debug mode that is off by default and never part of the demo or production path, and say so in the write-up. <!-- TODO: team to confirm -->
