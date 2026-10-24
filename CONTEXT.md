# Hackachusetts — Project Context

> Living context doc for our robotics hackathon entry. Keep this current — it's the single source of truth the team and any AI agents read first.

## Event

- **Hackathon:** Hackachusetts
- **Type:** Robotics hackathon, hardware-focused
- **Track:** Biotech / Healthcare
- **Duration:** <!-- TODO: e.g. 24h / 36h -->
- **Start / End:** <!-- TODO: dates + times -->
- **Repo:** https://github.com/eberhart441/hackathon10.24.26 (public, folder `hackachusetts`)
- **Challenge tracks:** Healthcare & Biotech, Robotics, Climate Tech, Civic Action. **We submit to Healthcare & Biotech.**
- **Deliverable:** public GitHub repo (with `/.kiro`), demo video under 3 min, text description, and a write-up on how we used Kiro. Full checklist below.
- **Submission deadline:** <!-- TODO: exact date/time and timezone from the Hackathon Website -->

### Track themes (from the track brief)

The Biotech / Healthcare track covers these focus areas:

1. Turning wearable data into better healthcare  **<-- our primary focus**
2. Keeping residents connected to health coverage
3. Improving healthcare access and coordination
4. Accelerating biotech innovation
5. Making clinical research more accessible

**Our approach:** build a wearable (theme 1) as the core, and where it's natural, borrow ideas from themes 2-5 (e.g. getting wearable data to the right care team, lowering the barrier to participating in clinical research, improving access for people who are underserved). These are secondary flavor, not scope creep. The wearable must work first.

## Submission Requirements (checklist)

Source: official rules. Missing any "must" can mean disqualification.

**Hard requirements**
- [ ] Team of **max 4 members**, all added on the submission form. One **Representative** is appointed to submit for the team.
- [ ] **Must use Kiro to build the project.** "Insufficient use of Kiro will result in disqualification" at the judges' sole discretion.
- [ ] Submit into one challenge track: **Healthcare & Biotech**.
- [ ] Text description explaining features and functionality.
- [ ] **Demo video, under 3 minutes** (judges don't have to watch past 3:00):
  - [ ] Shows the project **functioning on the actual device** it was built for
  - [ ] Public on YouTube, Vimeo, Facebook Video, or Youku, with the link on the submission form
  - [ ] No third-party trademarks, copyrighted music, or other material without permission (careful: don't show WHOOP/Apple/Fitbit logos, no copyrighted background music)
- [ ] **Public GitHub repo** containing all source code, assets, and instructions needed for the project to be functional (firmware, hub software, wiring diagram, BOM, build/flash steps).
- [ ] **`/.kiro` directory at the repo root.** Do NOT put `.kiro` or its subfolders in `.gitignore`.
- [ ] **Write-up on how Kiro was used** (see "Kiro Usage Log" below).
- [ ] Everything in English.
- [ ] Original work, solely owned by the team. Open source hardware/software is allowed only if we comply with its license and **build on top of it** with our own functionality.
- [ ] Project must not have been developed with financial or preferential support from the Sponsor/Administrator.

**Testing / access:** judges need a way to test the project (link, functioning demo, or test build), free of charge, until judging ends. They may judge from the description, images, and video alone, so **the video is likely the main thing they see**. A hardware project can't be tested remotely, so the repo instructions plus a clear video matter even more.

**After the deadline:** no changes allowed, except removing/replacing material that infringes a third-party mark, discloses PII, or is otherwise inappropriate (and only if permitted).

## Judging Criteria

Three equal-feeling buckets. Plan the pitch and demo around them.

1. **Potential Value**: is it widely useful, easy to use, accessible? Does it solve a real, clearly defined problem in a scalable, realistic way? Does the user journey address the unique needs of an affected community?
   - Considers: how unique/saturated the space is, accessibility/equity/adoption, and a pitch showing **who benefits and how it scales beyond the hackathon**.
2. **Implementation**: **how well and how deeply we used Kiro.** A thoughtful AI-development strategy, interesting integrations beyond the basics, variety of Kiro tools (IDE, CLI, Web, Crew), depth of understanding of each feature, and the amount of experimentation/strategic decisions.
3. **Quality and Design**: creativity, originality, polish. Unique public resources like datasets, solving a challenge in a surprising way, combining technologies in unexpected ways, an intuitive UI.

**Best Use of Kiro** bonus goes to the project with the highest **Implementation** score that is also in the top 10% of all projects.

## Prizes

| Prize | Amount / item |
|-------|---------------|
| Healthcare & Biotech 1st | $3,500 (split across the team) |
| Healthcare & Biotech 2nd | $1,000 |
| Healthcare & Biotech 3rd | $500 |
| Bonus: Best Use of Kiro | 1-year Kiro Pro Max subscription (~$1,200) |
| Bonus: Top 50 Finalists | WHOOP strap (50 total) |

- A project can win **one overall prize in a category plus up to two bonus prizes**.
- Top winners who meet eligibility (18+, experience in a general-purpose language such as C++/Python/TypeScript, enrolled in a Bachelor's or above in CS/STEM) can interview with AWS.
- Winners agree that the Sponsor can use names, likeness, and the submission for promotion for 3 years.

## Kiro Usage Log

Judges score "Implementation" on how well we used Kiro, and we must submit a write-up. **Log as we go**, because reconstructing it afterwards is painful. Everything Kiro-related must be committed in `/.kiro` in the hackathon repo.

| Kiro feature | What the judges ask | Our plan | Done? |
|--------------|---------------------|----------|-------|
| Tools (IDE / CLI / Web / Crew) | Which did we use, and how did they differ? | Use at least two (e.g. CLI for firmware/scripts, IDE for specs/hooks) and note the differences | [ ] |
| Spec-driven development | How did we structure the spec, and how did it compare to vibe coding? | Requirements -> design -> tasks for the core loop; keep a short "spec vs vibe" comparison note | [ ] |
| Agent hooks | What workflows did we automate? | Ideas: build/lint firmware on save, run host-side unit tests, keep `CONTEXT.md` current | [ ] |
| Steering docs | How did steering improve responses? | Steering for hardware constraints (pinout, 3.3V, I2C addresses), code style, health-data privacy rules | [ ] |
| MCP | What did extending Kiro enable? | Ideas: serial monitor / PlatformIO / datasheet lookup / GitHub. Pick ones that really help | [ ] |
| Property-based testing | Did PBT catch bugs unit tests missed? | Test pure signal logic on the host (filters, heart-rate peak detection, threshold/alert rules, packet encode/decode) | [ ] |
| Powers | Which powers or third-party integrations did we use? | Check what's installable and use any that fit | [ ] |

**Team decisions on Kiro usage (not just vibe coding)**
- Use **at least one MCP server** and show what it enabled that would have been hard otherwise.
- Use **at least one hook** (and more if they help) to automate a real workflow.
- Use **property-based testing in parallel with the physical build**: while the hardware is being wired up, write PBT for the pure logic (filters, peak detection, alert thresholds, packet encode/decode) on the host so software progress doesn't wait on hardware.
- Still use specs for the core loop. Keep notes on how that compared with vibe coding.

Running notes (add dated bullets as things happen):
- <!-- e.g. "Sat 10:40 - used the spec to generate the sensor-reading task list; saved ~1h" -->

**Repo hygiene for the Kiro requirement**
- The Git repo root is the project folder (`hackachusetts`), with `.kiro/` directly inside it (already started: `.kiro/steering/project.md`).
- Never add `.kiro` to `.gitignore`.
- Heads up: this session's workspace root is `Documents`, not `hackachusetts`. Open Kiro with `hackachusetts` as the workspace so specs, steering, and hooks are created in the right `.kiro/`.

## Team

- **Max 4 members.** One appointed Representative submits on the team's behalf.

<!-- TODO: fill in names + what each person owns -->
| Name | Role | Owns |
|------|------|------|
|      | Firmware |   |
|      | Hardware / mechanical |   |
|      | Software / app / dashboard |   |

## The Problem

<!-- TODO: Pick the specific problem within "wearable data -> better healthcare".
     - Who is the end user (patient / clinician / caregiver / research participant)?
     - What is painful about how it's done today?
     - Why does a wearable solve it better than software alone?
     Candidate angles (undecided, see Open Questions):
       a) Continuous vitals monitoring for a specific condition
       b) Getting wearable data in front of clinicians in a usable form (coordination)
       c) Low-cost wearable that lets people join remote clinical studies (research access)
       d) Wearable for people with limited access to care (access / coverage) -->

## The Solution (one-liner)

<!-- TODO: "A <wearable> that <does X> for <user> so they can <benefit>." -->

## System Overview

```
[ sensors (on body) ] --> [ ESP32 firmware ] --> [ BLE / WiFi ] --> [ RPi hub / touchscreen / dashboard ]
          ^                       |
          |                       v
      [ power ]           [ local feedback: LED / buzzer / display ]
```

This is a starting hypothesis based on the hardware we have. Redraw once the architecture is decided.

## Hardware

### Inventory (what we already have)

The team has a large pile of hobbyist-grade hardware, so we should design around parts in hand rather than ordering anything:

- ESP32 boards (several)
- Breadboards and jumper wires
- Raspberry Pi
- Touchscreen
- Standard sensor kit (the usual assortment, exact contents TBD)

<!-- TODO: do a quick physical inventory and list the exact sensor kit contents below -->

### Compute / MCU
- **Wearable node:** ESP32 (has BLE + WiFi built in, small, low power)
- **Hub / gateway / display:** Raspberry Pi + touchscreen (aggregates data, runs dashboard)
- **Why:** both are already on hand, and ESP32 -> RPi over BLE or WiFi is a well-trodden path.

### Sensors
<!-- TODO: confirm exactly what is in the sensor kit. Likely candidates for a wearable:
     - Pulse / heart rate (e.g. MAX30102 / MAX30100 / pulse sensor)  -> HR, SpO2
     - Temperature (DS18B20 / DHT / thermistor / MLX90614)            -> body temp
     - IMU / accelerometer (MPU6050 / ADXL345)                       -> motion, steps, falls
     - ECG (AD8232)                                                  -> ECG trace
     - GSR / skin conductance                                        -> stress proxy
     Fill in what we actually have, with interface (I2C/SPI/analog). -->
- Sensor 1 —
- Sensor 2 —

### Actuators / local feedback
<!-- TODO: LED, buzzer, vibration motor, OLED/touchscreen — or "none" -->
-

### Power
- **Source:** <!-- TODO: LiPo / coin cell / USB power bank. A wearable needs battery. -->
- **Regulation:** <!-- TODO: 3.3V rail; most ESP32 dev boards have an onboard LDO -->

### Bill of Materials (what we have vs. need)
| Part | Have? | Source | Notes |
|------|-------|--------|-------|
| ESP32 dev board | Yes | In hand | Several |
| Raspberry Pi | Yes | In hand | Hub / gateway |
| Touchscreen | Yes | In hand | Dashboard / local UI |
| Breadboards + jumpers | Yes | In hand | Prototyping |
| Sensor kit | Yes | In hand | Contents TBD |
| Battery / charging | ? | | Needed for true wearable |
| Enclosure / strap | ? | | 3D print or improvise |

## Firmware

- **Language:** <!-- TODO: C/C++ (Arduino framework) is the safe default for ESP32; MicroPython is faster to prototype -->
- **Toolchain / framework:** <!-- TODO: Arduino IDE / PlatformIO / ESP-IDF -->
- **Build command:** <!-- TODO: e.g. `pio run` -->
- **Flash command:** <!-- TODO: e.g. `pio run -t upload` -->
- **Monitor / serial:** <!-- TODO: e.g. `pio device monitor -b 115200` -->

### Firmware responsibilities
1. Read sensors at <!-- TODO: rate -->
2. Filter / process raw signal (e.g. smooth HR, detect motion)
3. Local feedback on thresholds (LED / buzzer)
4. Transmit data over <!-- TODO: BLE / WiFi / serial -->

## Software / App

- **Platform:** <!-- TODO: web dashboard on RPi touchscreen is the likely fit -->
- **Stack:** <!-- TODO -->
- **How it talks to the device:** <!-- TODO: BLE, WebSocket, MQTT, serial -->

## Milestones (hackathon timeline)

- [ ] **M1 - Hello world:** ESP32 flashes, serial prints. Proves toolchain works.
- [ ] **M2 - One sensor reading:** real data out of one sensor over serial.
- [ ] **M3 - Core loop:** sense -> process -> act/transmit end to end.
- [ ] **M4 - Comms:** data reaches the RPi / dashboard.
- [ ] **M5 - Wearable form factor:** on-body, battery powered, mounted.
- [ ] **M6 - Demo polish:** reliable happy-path run for judges, plus a clear pitch tying back to the track.
- [ ] **M7 - Submission package:** demo video (<3 min, device on camera, no copyrighted music/logos) uploaded public; text description; Kiro write-up; public GitHub repo with README, wiring/BOM, build + flash instructions, and `/.kiro` committed.

Reserve the last chunk of time for M7. Record the video with a safety margin, since the video is probably what most judges see.

## Decisions & Open Questions

**Decided**
- Track: Biotech / Healthcare.
- Primary theme: wearable data -> better healthcare.
- Secondary: borrow lightly from the other four themes where natural.
- Hardware: build from parts already in hand (ESP32s, RPi, touchscreen, sensor kit).

**Open**
- Which specific problem and end user? (see candidate angles under The Problem)
- Exact sensor kit contents?
- Which secondary theme(s) to lean on for the pitch?
- Firmware language and toolchain?
- BLE vs WiFi from wearable to hub?
- Hackathon length, team size (max 4), and roles?
- Exact submission deadline and timezone?
- Which public datasets could we use? (Quality and Design explicitly rewards this.)
- Which Kiro features beyond specs will we use (hooks, steering, MCP, PBT, powers)?

## Risks

- Sensor quality: kit-grade sensors are noisy. Don't promise clinical accuracy; frame as a prototype / screening-grade signal.
- Wearable form factor can eat time. Get the sensing loop working before building the enclosure.
- Health data privacy. Even for a demo, say how data would be handled (HIPAA-aware design, on-device or consented sharing).
- Scope creep across the five themes. Keep the wearable as the core.
- Disqualification risks: no `.kiro` in the repo, `.kiro` in `.gitignore`, thin Kiro usage, video over 3 minutes, copyrighted music or logos in the video, or a repo missing instructions to run it.
- Remote judging of hardware: judges can't touch the device, so the video has to show it working on-body and the README has to be reproducible.
- Privacy: don't put real personal health data or identifiable faces/info in the video or repo. Use test data or team members who consent.

## Links

- Repo: <!-- TODO -->
- Devpost / submission: <!-- TODO -->
- Datasheets: <!-- TODO -->
