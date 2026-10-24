---
inclusion: always
---

# Project steering

- Read `CONTEXT.md` and `AGENTS.md` at the repo root before making changes. They hold the event rules, architecture, privacy rules, and honest limits. The old health-wearable plan is cancelled; ignore any leftover references to it.
- Project: WiFi (CSI) sensing on ESP32 nodes to find people in a building during a fire and tell firefighters which rooms to search first. Track: Civic Action, theme V2.
- **Never clear a room.** "No motion detected" does not mean "empty". UI and docs say "Search priority" and "Motion last seen", never "Clear" or "Empty, confirmed".
- **Detect, never identify.** Room-level detail at most. Raw CSI never leaves a node. No MAC addresses, device identifiers, or phone sniffing. Incident data is stored only while an incident is open.
- Do not claim still-body (breathing) detection, identification, or meter-level position. Mark anything experimental as such.
- Keep decision logic (state machine, flag rule, trails, packet encode/decode, calibration) as pure functions separate from hardware I/O so it can be tested with Hypothesis on the host.
- Do not add `.kiro/` to `.gitignore`, and never commit secrets or recordings of non-consenting people.
