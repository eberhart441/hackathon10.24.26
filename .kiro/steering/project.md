---
inclusion: always
---

# Project steering

- Read `CONTEXT.md` and `AGENTS.md` at the repo root before making changes. They hold the event rules, architecture, and ground rules.
- This is a Healthcare & Biotech hackathon prototype. Never claim it is a medical device or that it prevents SIDS.
- Do not add `.kiro/` to `.gitignore`, and never commit secrets or real personal health data.
- Keep decision logic pure and testable on the host; keep hardware I/O thin.
