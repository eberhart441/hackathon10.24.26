"""Put the walls of a walls-only DXF, and the boards of an rs-view layout, into the hub floor plan.

    hub/.venv/Scripts/python tools/walls_to_floorplan.py "floor plans/walls_only.dxf" --layout firmware/tools/layouts/conference-room.json --layout-origin 0 114 --write hub/config/floorplan.json

What it does:
  - walls: every LINE / LWPOLYLINE of the DXF (read with roomsense_hub.dxf_walls, no ezdxf needed)
    becomes a loop in the floor's "walls" list, in metres. The dashboard fills the space between
    the loops (even-odd), so the wall thickness and the door openings are exactly the drawing's;
  - frame: the floor's origin (0, 0) is the drawing's bottom-left corner (minimum x and y over all
    wall points), y up, as the floor plan convention wants;
  - boards: --layout is the motion-map layout used by rs-view (feet from the sensed room's top-left
    inside corner, y down); --layout-origin is that corner in DXF units (the same numbers as
    `python -m roomsense_hub.dxf_walls --origin`). Each board is put in the floor plan room whose
    polygon contains it, so a board in the hallway counts for the hallway, not for the room.

The rooms themselves (ids, names, polygons, doors) stay hand-edited in the floor plan: a
walls-only drawing does not say where one room ends and the hallway begins.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "firmware" / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from roomsense_hub.dxf_walls import read_dxf_text  # noqa: E402

from dxf_to_floorplan import (  # noqa: E402
    FT, SOURCE_DATE, UNIT_NAMES, ConvertError, Vec, _seg_dist, dumps_plan, point_in_polygon, unit_scale,
    validate_plan,
)


def _r(v: float) -> float:
    return round(v, 4) + 0.0  # + 0.0 turns -0.0 into 0.0


def wall_frame(lines: list[list[Vec]]) -> Vec:
    """The floor origin in DXF units: the drawing's minimum x and y."""
    pts = [p for line in lines for p in line]
    if not pts:
        raise ConvertError("The DXF has no LINE or LWPOLYLINE entities, so there are no walls to read.")
    return min(x for x, _ in pts), min(y for _, y in pts)


def walls_m(lines: list[list[Vec]], scale: float, origin: Vec) -> list[list[list[float]]]:
    """DXF polylines -> floor plan wall loops in metres. A repeated closing point is dropped (loops
    are closed implicitly)."""
    ox, oy = origin
    out = []
    for line in lines:
        pts = [[_r((x - ox) * scale), _r((y - oy) * scale)] for x, y in line]
        if len(pts) > 2 and pts[0] == pts[-1]:
            pts.pop()
        out.append(pts)
    return out


def layout_boards(layout: dict, layout_origin: Vec, scale: float, origin: Vec) -> tuple[list[dict], list[dict]]:
    """rs-view layout (feet from layout_origin, y down) -> nodes and links (metres in the floor frame).
    Transmitters are named TX1, TX2, ... by first appearance, as in dxf_to_floorplan.layout_nodes."""
    lx, ly = layout_origin
    ox, oy = origin

    def conv(p) -> list[float]:
        x_dxf = lx + float(p[0]) * FT / scale
        y_dxf = ly - float(p[1]) * FT / scale
        return [_r((x_dxf - ox) * scale), _r((y_dxf - oy) * scale)]

    tx_ids: dict[tuple[float, float], str] = {}
    tx_nodes: list[dict] = []
    rx_nodes: list[dict] = []
    links: list[dict] = []
    for rx_id, v in layout["links"].items():
        key = (float(v["tx"][0]), float(v["tx"][1]))
        if key not in tx_ids:
            tx_ids[key] = f"TX{len(tx_ids) + 1}"
            tx_nodes.append({"id": tx_ids[key], "role": "TX", "pos": conv(v["tx"]), "h": 1})
        rx_nodes.append({"id": rx_id, "role": "RX", "pos": conv(v["rx"]), "h": 1})
        links.append({"tx": tx_ids[key], "rx": rx_id})
    return tx_nodes + rx_nodes, links


def room_of(p: Vec, rooms: list[dict], warn=None) -> str:
    """The room whose polygon contains p; a board standing in a wall goes to the nearest room."""
    for r in rooms:
        if point_in_polygon(p, [tuple(q) for q in r["polygon"]]):
            return r["id"]

    def dist(r: dict) -> float:
        poly = [tuple(q) for q in r["polygon"]]
        return min(_seg_dist(p, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))

    best = min(rooms, key=dist)
    if warn is not None:
        warn(f"WARNING: a board at ({p[0]:.2f}, {p[1]:.2f}) m is in no room; using the nearest, {best['id']} "
             f"({dist(best):.2f} m away).")
    return best["id"]


def update_floorplan(plan: dict, floor_id: str, walls: list, nodes: list[dict] | None, links: list[dict] | None,
                     source: str, warn=None) -> dict[str, Any]:
    plan = json.loads(json.dumps(plan))
    floor = next((f for f in plan["floors"] if f["id"] == floor_id), None)
    if floor is None:
        raise ConvertError(f"The floor plan has no floor {floor_id!r}.")
    floor["walls"] = walls
    if nodes is not None:
        for n in nodes:
            n["room"] = room_of(tuple(n["pos"]), floor["rooms"], warn)
        plan["nodes"] = [{"id": n["id"], "role": n["role"], "room": n["room"], "pos": n["pos"], "h": n["h"]}
                         for n in nodes]
        plan["links"] = links
    plan["_source"] = source
    return plan


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dxf", type=Path)
    p.add_argument("--floor", default="F1", help="floor plan floor to give the walls (default F1)")
    p.add_argument("--layout", type=Path, help="rs-view layout JSON with the board positions")
    p.add_argument("--layout-origin", type=float, nargs=2, metavar=("X", "Y"),
                   help="the layout's origin (the sensed room's top-left inside corner) in DXF units")
    p.add_argument("--write", type=Path, help="floor plan JSON to update in place")
    args = p.parse_args(argv)
    warn = lambda m: print(m, file=sys.stderr)  # noqa: E731

    try:
        if args.layout and not args.layout_origin:
            raise ConvertError("--layout needs --layout-origin (the room's top-left inside corner in DXF units).")
        lines, units = read_dxf_text(args.dxf.read_text(encoding="utf-8", errors="replace"))
        scale = unit_scale(units)
        origin = wall_frame(lines)
        walls = walls_m(lines, scale, origin)
        nodes = links = None
        if args.layout:
            nodes, links = layout_boards(json.loads(args.layout.read_text(encoding="utf-8")),
                                         tuple(args.layout_origin), scale, origin)
        source = (f"Walls of {args.floor} from {args.dxf.as_posix()} ({UNIT_NAMES[units]}; floor origin = DXF "
                  f"({origin[0]:g}, {origin[1]:g}))"
                  + (f"; boards from {args.layout.as_posix()} (origin DXF ({args.layout_origin[0]:g}, "
                     f"{args.layout_origin[1]:g}))" if args.layout else "")
                  + f" by tools/walls_to_floorplan.py on {SOURCE_DATE}. Rooms are hand-edited.")
        if not args.write:
            out: dict[str, Any] = {"walls": walls}
            if nodes is not None:
                out["nodes"], out["links"] = nodes, links
            print(dumps_plan(out))
            return 0
        plan = json.loads(args.write.read_text(encoding="utf-8"))
        new = update_floorplan(plan, args.floor, walls, nodes, links, source, warn)
        errors = validate_plan(new)
        if errors:
            raise ConvertError("The updated floor plan would be invalid: " + "; ".join(errors))
        args.write.write_text(dumps_plan(new) + "\n", encoding="utf-8")
        print(f"Updated {args.write}: {len(walls)} wall loops on {args.floor}"
              + (f", {len(new['nodes'])} boards" if nodes is not None else ""))
        for n in new["nodes"]:
            print(f"  {n['id']:<4} {n['role']}  room {n['room']:<4} at {n['pos']}")
        return 0
    except (ConvertError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
