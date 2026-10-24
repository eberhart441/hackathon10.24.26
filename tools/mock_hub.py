"""Mock hub: serves the PWA against the scripted incident (pwa-dashboard Req 21).

Usage (repo root):  python tools/mock_hub.py [--check]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub.web.app import create_app  # noqa: E402
from hub.web.settings import Settings  # noqa: E402
from tools.mock_incident import ScriptedIncident, nodes_from_floorplan, rooms_from_floorplan  # noqa: E402


def build_app():
    settings = Settings.load()
    plan = json.loads(settings.floorplan_file.read_text(encoding="utf-8"))
    source = ScriptedIncident(rooms_from_floorplan(plan), time.monotonic, nodes=nodes_from_floorplan(plan))
    return create_app(source, settings)


def main(argv: list[str]) -> int:
    app = build_app()
    if "--check" in argv:
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            status = client.get("/").status_code
        print(f"mock hub check: GET / -> {status}")
        return 0 if status < 500 else 1
    import asyncio

    from hub.web.listeners import cert_ok, local_addresses, plan_listeners, serve, url

    settings = Settings.load()
    listeners, logs = plan_listeners(settings, cert_ok(settings), local_addresses())
    for line in logs:
        print(line)
    if not listeners:
        print("No usable listen address. Check HUB_BIND_HOSTS.")
        return 1
    for lst in listeners:
        print(f"Listening on {url(lst)}")
    asyncio.run(serve(app, listeners, settings))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
