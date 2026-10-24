"""Read wall lines from a DXF floor plan and convert them to layout coordinates.

Layout coordinates are feet, measured from the top-left inside corner of the sensed room, with
y going DOWN the page (DXF y goes up). Only LINE and LWPOLYLINE entities are read, which is what
simple floor-plan exports contain.

    python -m roomsense_hub.dxf_walls "floor plans/walls_only.dxf" --origin 0 114
        prints the walls as JSON, ready to paste into a layout's "walls" key.

--origin is the room's top-left inside corner in the DXF's own units; --units-per-ft is 12 for a
drawing in inches (DXF $INSUNITS = 1), 1 for feet.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

Point = tuple[float, float]


def read_dxf_lines(path: Path) -> list[list[Point]]:
    """Every LINE and LWPOLYLINE as a list of points, in the DXF's own units. Closed polylines repeat
    their first point at the end."""
    return read_dxf_text(Path(path).read_text(encoding="utf-8", errors="replace"))[0]


def read_dxf_text(text: str) -> tuple[list[list[Point]], int | None]:
    """Like read_dxf_lines, from the file's text; also returns the drawing's $INSUNITS (None if absent)."""
    raw = text.splitlines()
    pairs = [(raw[i].strip(), raw[i + 1].strip()) for i in range(0, len(raw) - 1, 2)]
    units = None
    for k in range(len(pairs) - 1):
        if pairs[k] == ("9", "$INSUNITS") and pairs[k + 1][0] == "70":
            units = int(pairs[k + 1][1])
            break
    lines: list[list[Point]] = []
    i = 0
    while i < len(pairs):
        code, value = pairs[i]
        if code == "0" and value in ("LINE", "LWPOLYLINE"):
            j = i + 1
            fields: list[tuple[str, str]] = []
            while j < len(pairs) and pairs[j][0] != "0":
                fields.append(pairs[j])
                j += 1
            if value == "LINE":
                d = dict(fields)
                lines.append([(float(d["10"]), float(d["20"])), (float(d["11"]), float(d["21"]))])
            else:
                pts: list[Point] = []
                x = None
                closed = False
                for k, v in fields:
                    if k == "70":
                        closed = int(v) & 1 == 1
                    elif k == "10":
                        x = float(v)
                    elif k == "20" and x is not None:
                        pts.append((x, float(v)))
                if closed and pts and pts[0] != pts[-1]:
                    pts.append(pts[0])
                if len(pts) >= 2:
                    lines.append(pts)
            i = j
            continue
        i += 1
    return lines, units


def to_layout(lines: list[list[Point]], origin: Point, units_per_ft: float) -> list[list[Point]]:
    ox, oy = origin
    return [[(round((x - ox) / units_per_ft, 3), round((oy - y) / units_per_ft, 3)) for x, y in line]
            for line in lines]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dxf", type=Path)
    p.add_argument("--origin", type=float, nargs=2, required=True, metavar=("X", "Y"),
                   help="the room's top-left inside corner, in DXF units")
    p.add_argument("--units-per-ft", type=float, default=12.0, help="12 for inches (default), 1 for feet")
    args = p.parse_args(argv)
    walls = to_layout(read_dxf_lines(args.dxf), tuple(args.origin), args.units_per_ft)
    json.dump(walls, sys.stdout)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
