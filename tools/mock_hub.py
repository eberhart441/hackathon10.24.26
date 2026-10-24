"""Run the hub web layer with the scripted mock incident (all data labelled SIMULATED).

    hub/.venv/Scripts/python tools/mock_hub.py              # settings from env / hub/.env
    hub/.venv/Scripts/python tools/mock_hub.py --host 127.0.0.1 --port 8000 --speed 4
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub.mock_source import ScriptedSource  # noqa: E402
from hub.serve import run  # noqa: E402
from hub.settings import Settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", action="append", help="listen address (repeatable); overrides HUB_BIND_HOSTS")
    parser.add_argument("--port", type=int, help="overrides HUB_PORT")
    parser.add_argument("--speed", type=float, default=float(os.environ.get("MOCK_SPEED", "1")),
                        help="timeline speed-up factor (env MOCK_SPEED, default 1)")
    args = parser.parse_args()

    settings = Settings.load()
    if args.host:
        settings = replace(settings, bind_hosts=tuple(args.host))
    if args.port:
        settings = replace(settings, port=args.port)
    run(ScriptedSource(speed=args.speed), settings)


if __name__ == "__main__":
    main()
