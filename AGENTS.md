# AGENTS.md

Guidance for AI agents (Kiro and others) working in this repo. Read `CONTEXT.md` first. It is the source of truth for the event, rules, architecture, and open questions.

## Project

Hackachusetts hackathon entry, **Healthcare & Biotech** track. A cheap, simple wearable (ESP32 + IMU + temperature sensor) with a self-hosted web dashboard, aimed at infant sleep-safety awareness. Firmware is written in C++ (Arduino framework via PlatformIO). Dev tooling includes MCP servers for serial/flash and synthetic data.

## Ground rules

- **Not a medical device.** Never write code, UI text, docs, or pitch copy claiming the device prevents SIDS or diagnoses anything. Use "prototype" and "sleep-safety awareness".
- **No real personal health data.** Use synthetic or consenting-adult data only. Never commit real infant data, faces, or identifying information.
- **No secrets in git.** WiFi passwords, tokens, and topic names go in `secrets.h` / `.env` (both git-ignored). Commit a `secrets.example.h` instead.
- **Never git-ignore `.kiro/`.** The competition requires `/.kiro` at the repo root. Do not add `.kiro` or its subfolders to `.gitignore`.
- **Everything must run from this repo.** Judges need source, assets, wiring/BOM, and build/flash instructions. Keep the README accurate.
- **No third-party trademarks or copyrighted material** in assets or demo content (no WHOOP/other brand logos, no copyrighted music).
- **Auth on every network endpoint.** The device exposes data over HTTP; require a token on the API and any demo/inject endpoint, and keep demo mode off by default.

## Engineering conventions

- Keep decision logic (position detection, alert state machine, thresholds, packet encode/decode) as **pure functions** separate from hardware I/O, so it can be unit and property-tested on the host (PlatformIO `native` environment).
- Treat signal loss as its own state. A missing or stale sensor must never be reported as a normal reading.
- Prefer small, reviewable changes. Update `CONTEXT.md` (decisions, open questions, Kiro usage log) when something is decided.
- Hardware constraints: ESP32 is 3.3V logic; confirm I2C addresses and pins before writing firmware; keep the served web page small.

## Agent skills

### Domain docs

Single-context: one `CONTEXT.md` at the repo root. Record notable decisions and open questions there.

## Kiro usage (for the competition write-up)

Log notable Kiro usage (specs, hooks, steering, MCP, property-based testing, powers) in the "Kiro Usage Log" section of `CONTEXT.md` as it happens.
