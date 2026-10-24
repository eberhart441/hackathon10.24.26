# AGENTS.md

Guidance for AI agents (Kiro and others) working in this repo. Read `CONTEXT.md` first. It is the source of truth for the event, rules, architecture, privacy rules, and open questions.

## Project

Hackachusetts hackathon entry, **Civic Action** track (theme V2, Responsive and resilient communities). A network of cheap ESP32 nodes uses WiFi CSI to detect movement through smoke and walls during a fire, follows people room by room, and flags rooms where a trail went still with no exit, so firefighters know which rooms to search first. Pipeline: ESP32 nodes -> ESP-NOW -> ESP32 gateway -> Raspberry Pi (Python, FastAPI) -> web dashboard.

The earlier health-wearable plan is cancelled.

## Ground rules

- **Never clear a room.** "No motion detected" is not "empty". UI text and docs use "Search priority" and "Motion last seen", never "Clear" or "Empty, confirmed".
- **Detect, never identify.** No identity of any kind. Room-level detail at most.
- **Privacy:** raw CSI never leaves a sensor node; no MAC addresses, device identifiers, or phone sniffing; incident data (trails, logs) is stored only while an incident is open.
- **Do not overclaim.** No claims of still-body (breathing) detection, identification, or meter-level position. Label anything experimental as such.
- **Consent:** demo footage and test data use consenting teammates only, in a mock room.
- **No secrets in git.** WiFi credentials, tokens, and keys go in git-ignored files; commit an example file instead.
- **Never git-ignore `.kiro/`.** The competition requires `/.kiro` at the repo root. Do not add `.kiro` or its subfolders to `.gitignore`.
- **Everything must run from this repo.** Judges need source, assets, wiring/node layout, BOM, and build/flash/run instructions. Keep the README accurate.
- **No third-party trademarks or copyrighted material** in assets or demo content.
- **Auth on network endpoints.** The Pi server and dashboard expose data over HTTP/WebSocket; flag and, where practical, require a token. Do not expose them to the internet.

## Engineering conventions

- Keep decision logic (zone fusion, calibration, room state machine, flag rule, trails, packet encode/decode) as **pure functions** separate from hardware I/O, so it can be unit- and property-tested on the host (Python + Hypothesis).
- Test privacy invariants: outbound data has no identifier fields and nothing finer than room level; no incident data is stored when no incident is open.
- A room never becomes EXITED without a doorway-crossing event; trails only move between adjacent rooms.
- Raw CSI streaming to the Pi is a dev-only debug mode, off by default, never part of the demo or production path.
- ESP32 nodes: the team's boards are **ESP32-C3** (CSI is supported per esp-csi; use `idf.py set-target esp32c3`). Buy the same model for any extra boards so all nodes match. Firmware is C (ESP-IDF) built on Espressif's esp-csi `csi_send` / `csi_recv` examples.
- Prefer small, reviewable changes. Update `CONTEXT.md` (decisions, open questions, Kiro usage log) when something is decided.

## Agent skills

### Issue tracker

Issues and specs live as local markdown files under `.scratch/<feature-slug>/`.

### Domain docs

Single-context: one `CONTEXT.md` at the repo root. Record notable decisions and open questions there.

## Kiro usage (for the competition write-up)

Log notable Kiro usage (specs, hooks, steering, MCP, property-based testing, powers) in the "Kiro Plan & Usage Log" section of `CONTEXT.md` as it happens.
