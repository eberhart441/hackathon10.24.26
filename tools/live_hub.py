"""Run the hub web layer on real receivers (or a replay / simulated boards).

    hub/.venv/Scripts/python tools/live_hub.py --port COM8 --port COM9 --port COM10 --port COM11
    hub/.venv/Scripts/python tools/live_hub.py --simulate-boards        # no hardware
    hub/.venv/Scripts/python tools/live_hub.py --replay firmware/tools/tests/fixtures/sample_capture.log

Receivers are matched to rooms by hub/config/floorplan.json (nodes with role RX). Rooms marked
"simulated" there are filled from the scripted mock unless --no-sim is given.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub import room_engine  # noqa: E402
from hub.live_source import LiveSource  # noqa: E402
from hub.serve import run  # noqa: E402
from hub.settings import Settings  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_argument_group("data (pick one or more)")
    src.add_argument("--port", action="append", default=[], help="a receiver's serial port (repeatable)")
    src.add_argument("--replay", type=Path, help="replay a captured serial log in a loop")
    src.add_argument("--simulate-boards", action="store_true", help="fake receivers from firmware/tools")
    p.add_argument("--baud", type=int, default=921600)
    p.add_argument("--floorplan", type=Path, default=ROOT / "hub" / "config" / "floorplan.json")
    p.add_argument("--layout", type=Path, default=ROOT / "firmware" / "tools" / "layouts" / "demo-room.json",
                   help="board layout for --simulate-boards")
    p.add_argument("--hold-s", type=float, default=room_engine.HOLD_S,
                   help="seconds a room stays POSSIBLE after motion stops (spec: 300; shorten for demos)")
    p.add_argument("--no-sim", action="store_true", help="show only live rooms (no SIMULATED rooms)")
    p.add_argument("--sim-speed", type=float, default=1.0, help="speed of the simulated rooms' timeline")
    p.add_argument("--host", action="append", help="listen address (repeatable); overrides HUB_BIND_HOSTS")
    p.add_argument("--http-port", type=int, help="overrides HUB_PORT")
    args = p.parse_args(argv)

    if not (args.port or args.replay or args.simulate_boards):
        p.error("give at least one --port, or --replay, or --simulate-boards")

    try:
        source = LiveSource(args.floorplan, hold_s=args.hold_s, with_sim=not args.no_sim, sim_speed=args.sim_speed)
    except ValueError as exc:
        print(f"Cannot start: {exc}", file=sys.stderr)
        return 2
    for port in args.port:
        source.add_serial_port(port, args.baud)
    if args.replay:
        source.add_replay(args.replay)
    if args.simulate_boards:
        source.add_board_simulator(args.layout)

    settings = Settings.load()
    if args.host:
        settings = replace(settings, bind_hosts=tuple(args.host))
    if args.http_port:
        settings = replace(settings, port=args.http_port)
    run(source, settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
