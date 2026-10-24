"""Turn an architectural DXF of one room into the hub's floor plan (hub/config/floorplan.json).

    hub/.venv/Scripts/python tools/dxf_to_floorplan.py "floor plans/conference_room.dxf" --room-id R1 --height 9ft4in --layout firmware/tools/layouts/demo-room.json --write hub/config/floorplan.json

What it reads from the DXF:
  - the room outline: the closed polyline on layer A-WALL (inner boundary, then outer boundary);
  - doors: arcs on layer A-DOOR-SWNG (centre = hinge, radius = door width);
  - the room name: texts on layer A-AREA-IDEN (the "... SF" area text is kept only as a note).

Overrides: --width / --height replace a measured dimension the drawing got wrong. They move only
the far wall (max x or max y) and print a WARNING with the difference.

Node positions are not in the DXF. --layout takes the motion-map layout used by rs-view
(firmware/tools/layouts/*.json, feet from the TOP-LEFT corner, y down) so the PWA and the
viewer place the boards in the same spots.

The floor plan convention: metres, origin at the room's inside bottom-left corner, y up, polygon
counter-clockwise starting at the bottom-left vertex, edge i runs from vertex i to vertex i+1, and
a door sits on an edge `offset` metres from the edge's start vertex. "hinge" says which end of the
opening the door turns on ("start" = nearer the edge's start vertex, "end" = the other end).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

Vec = tuple[float, float]

UNIT_TO_M = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0}
UNIT_NAMES = {1: "inches", 2: "feet", 4: "millimetres", 5: "centimetres", 6: "metres"}
FT = 0.3048
IN = 0.0254
EPS = 1e-6
ON_EDGE_TOL_M = 0.02  # a hinge within 2 cm of a wall counts as on it
GAP_MISMATCH_WARN_M = IN  # door width vs wall gap
LAYOUT_MISMATCH_WARN_M = 0.03
SOURCE_DATE = "2026-10-24"


class ConvertError(Exception):
    """A problem with the input the user can fix."""


# ---------------------------------------------------------------- lengths and units


_LEN_TOKEN = re.compile(r"\s*(\d+(?:\.\d+)?)\s*(ft|feet|foot|'|in|inch|inches|\"|mm|cm|m)\s*", re.I)
_LEN_FACTOR = {"ft": FT, "feet": FT, "foot": FT, "'": FT, "in": IN, "inch": IN, "inches": IN, '"': IN,
               "mm": 0.001, "cm": 0.01, "m": 1.0}


def parse_length(text: str) -> float:
    """'9ft4in', '112in', '2.845m', "9' 4\"" -> metres."""
    s = text.strip()
    pos = 0
    total = 0.0
    found = False
    while pos < len(s):
        m = _LEN_TOKEN.match(s, pos)
        if not m:
            raise ConvertError(f"Cannot read the length {text!r}. Use forms like 9ft4in, 112in or 2.845m.")
        total += float(m.group(1)) * _LEN_FACTOR[m.group(2).lower()]
        pos = m.end()
        found = True
    if not found or total <= 0:
        raise ConvertError(f"Cannot read the length {text!r}. Use forms like 9ft4in, 112in or 2.845m.")
    return total


def unit_scale(insunits: int | None) -> float:
    if insunits not in UNIT_TO_M:
        raise ConvertError(
            f"The DXF's drawing units ($INSUNITS={insunits}) are not inches, feet, mm, cm or metres. "
            "Set the units in the CAD program and export again."
        )
    return UNIT_TO_M[insunits]


# ---------------------------------------------------------------- pure geometry


def signed_area(poly: list[Vec]) -> float:
    return sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
               for i in range(len(poly))) / 2


def _near(a: Vec, b: Vec, tol: float = 1e-6) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _collinear(a: Vec, b: Vec, c: Vec, tol: float = 1e-9) -> bool:
    cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    scale = max(1.0, math.dist(a, b) * math.dist(a, c))
    return abs(cross) <= tol * scale


def interior_loop(outline: list[Vec]) -> tuple[list[Vec], list[tuple[Vec, Vec]]]:
    """Split an A-WALL outline (inner boundary + outer boundary in one polyline) into the room's
    inner loop. Returns the inner vertices in drawing order and the "bridges": segments that close
    the loop where the outline left the inner boundary (door gaps)."""
    pts = [p for i, p in enumerate(outline) if i == 0 or not _near(p, outline[i - 1])]
    if len(pts) > 1 and _near(pts[0], pts[-1]):
        pts.pop()
    if len(pts) < 3:
        raise ConvertError("The A-WALL outline has fewer than 3 points.")
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    tol = 1e-6 * max(1.0, maxx - minx, maxy - miny)

    def inside(p: Vec) -> bool:
        return minx + tol < p[0] < maxx - tol and miny + tol < p[1] < maxy - tol

    flags = [inside(p) for p in pts]
    if all(flags):
        return pts, []  # just a single loop: the outline is the room
    if not any(flags):
        return pts, []  # a single wall line drawn as the room boundary
    # Longest cyclic run of inner vertices.
    n = len(pts)
    start = next(i for i in range(n) if flags[i] and not flags[i - 1])
    runs: list[list[int]] = []
    i = start
    for _ in range(n):
        if flags[i] and not flags[i - 1]:
            runs.append([])
        if flags[i]:
            runs[-1].append(i)
        i = (i + 1) % n
    run = max(runs, key=len)
    loop = [pts[k] for k in run]
    bridges = [(loop[-1], loop[0])]
    return loop, bridges


def normalize_polygon(poly: list[Vec]) -> list[Vec]:
    """Drop duplicate and collinear vertices, orient counter-clockwise, start at bottom-left."""
    pts = [p for i, p in enumerate(poly) if not _near(p, poly[i - 1])] if len(poly) > 1 else list(poly)
    changed = True
    while changed and len(pts) > 3:
        changed = False
        for i in range(len(pts)):
            if _collinear(pts[i - 1], pts[i], pts[(i + 1) % len(pts)]):
                del pts[i]
                changed = True
                break
    if len(pts) < 3 or abs(signed_area(pts)) < EPS:
        raise ConvertError("The room outline has no area.")
    if signed_area(pts) < 0:
        pts.reverse()
    k = min(range(len(pts)), key=lambda i: (round(pts[i][1], 9), round(pts[i][0], 9)))
    return pts[k:] + pts[:k]


def point_in_polygon(p: Vec, poly: list[Vec]) -> bool:
    x, y = p
    inside = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _project(p: Vec, a: Vec, b: Vec) -> tuple[float, float]:
    """Distance along a->b (metres) and distance from the line."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    t = (p[0] - a[0]) * ux + (p[1] - a[1]) * uy
    off = abs((p[0] - a[0]) * uy - (p[1] - a[1]) * ux)
    return t, off


def door_on_polygon(poly: list[Vec], hinge: Vec, radius: float, start_deg: float, end_deg: float) -> dict[str, Any]:
    """Floor plan door fields for a swing arc (centre = hinge, radius = width, CCW from start to end)."""
    best = None
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        t, off = _project(hinge, a, b)
        length = math.dist(a, b)
        if off <= ON_EDGE_TOL_M and -ON_EDGE_TOL_M <= t <= length + ON_EDGE_TOL_M:
            if best is None or off < best[1]:
                best = (i, off, t, a, b, length)
    if best is None:
        raise ConvertError(f"A door hinge at ({hinge[0]:.3f}, {hinge[1]:.3f}) m is not on any wall of the room.")
    edge, _, t_hinge, a, b, length = best
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length

    # The arc end that runs along the wall is where the closed door's latch is.
    def along(deg: float) -> float:
        r = math.radians(deg)
        return math.cos(r) * ux + math.sin(r) * uy

    a0, a1 = along(start_deg), along(end_deg)
    sign = a0 if abs(a0) >= abs(a1) else a1
    t_latch = t_hinge + (radius if sign > 0 else -radius)
    lo, hi = sorted((t_hinge, t_latch))
    if lo < -ON_EDGE_TOL_M or hi > length + ON_EDGE_TOL_M:
        raise ConvertError(f"A {radius:.3f} m door on edge {edge} does not fit the {length:.3f} m wall.")
    lo, hi = max(0.0, lo), min(length, hi)

    sweep = (end_deg - start_deg) % 360 or 360
    mid = math.radians(start_deg + sweep / 2)
    mid_pt = (hinge[0] + radius * 0.5 * math.cos(mid), hinge[1] + radius * 0.5 * math.sin(mid))
    swing = "in" if point_in_polygon(mid_pt, poly) else "out"
    return {"edge": edge, "offset": lo, "width": hi - lo, "swing": swing,
            "hinge": "start" if t_hinge <= t_latch else "end"}


def apply_overrides(poly: list[Vec], points: list[Vec], width: float | None, height: float | None,
                    warn) -> tuple[list[Vec], list[Vec]]:
    """Move the far wall(s) so the room measures width x height. `points` (door hinges) on a moved
    wall move with it. Returns the new polygon and points."""
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    tol = 1e-6 * max(1.0, maxx - minx, maxy - miny)
    new_poly, new_pts = list(poly), list(points)
    for value, lo, hi, axis, name in ((width, minx, maxx, 0, "width"), (height, miny, maxy, 1, "height")):
        if value is None:
            continue
        target = lo + value
        diff = value - (hi - lo)
        if abs(diff) > 1e-4:
            warn(f"WARNING: the DXF room {name} is {(hi - lo):.4f} m ({(hi - lo) / IN:.1f} in); using {value:.4f} m "
                 f"({value / IN:.1f} in) from --{name}. The drawing is off by {diff / IN:+.1f} in; fix the DXF.")

        def move(p: Vec) -> Vec:
            if abs(p[axis] - hi) <= tol:
                return (target, p[1]) if axis == 0 else (p[0], target)
            return p

        new_poly = [move(p) for p in new_poly]
        new_pts = [move(p) for p in new_pts]
    return new_poly, new_pts


def room_name(texts: list[tuple[str, Vec]]) -> tuple[str | None, list[str]]:
    """Join area-ID texts top to bottom, skipping the area ("123.5 SF"). Returns (name, notes)."""
    words, notes = [], []
    for txt, _ in sorted(texts, key=lambda t: -t[1][1]):
        t = txt.strip()
        if not t:
            continue
        if re.search(r"\b(SF|SQ\.? ?FT|M2|M²)\s*$", t, re.I):
            notes.append(t)
        else:
            words.append(t.capitalize() if t.isalpha() else t)
    return (" ".join(words) or None), notes


def layout_nodes(layout: dict, warn=None, room_wh: Vec | None = None) -> tuple[list[dict], list[dict]]:
    """rs-view layout (feet from the top-left, y down) -> floor plan nodes and links (metres, y up)."""
    w_ft, h_ft = (float(v) for v in layout["room"])
    if room_wh is not None and warn is not None:
        dw, dh = abs(w_ft * FT - room_wh[0]), abs(h_ft * FT - room_wh[1])
        if dw > LAYOUT_MISMATCH_WARN_M or dh > LAYOUT_MISMATCH_WARN_M:
            warn(f"WARNING: the layout room is {w_ft * FT:.3f} x {h_ft * FT:.3f} m but the floor plan room is "
                 f"{room_wh[0]:.3f} x {room_wh[1]:.3f} m; board positions may be off.")

    def conv(p) -> list[float]:
        return [_r(float(p[0]) * FT), _r((h_ft - float(p[1])) * FT)]

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


def crew_slot(poly: list[Vec], doors: list[dict], current: Vec | None, inset: float = 0.4) -> list[float]:
    """Keep the existing slot if it sits well inside the room, else use the corner farthest from a door."""
    def edge_dist(p: Vec) -> float:
        return min(_seg_dist(p, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))

    if current is not None and point_in_polygon(current, poly) and edge_dist(current) >= 0.3:
        return [round(current[0], 4), round(current[1], 4)]
    door_pts = []
    for d in doors:
        a, b = poly[d["edge"]], poly[(d["edge"] + 1) % len(poly)]
        L = math.dist(a, b)
        t = (d["offset"] + d["width"] / 2) / L
        door_pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    candidates = []
    for p in poly:
        dx, dy = cx - p[0], cy - p[1]
        n = math.hypot(dx, dy) or 1
        q = (p[0] + dx / n * inset * math.sqrt(2), p[1] + dy / n * inset * math.sqrt(2))
        if point_in_polygon(q, poly):
            candidates.append(q)
    if not candidates:
        return [round(cx, 4), round(cy, 4)]
    best = max(candidates, key=lambda q: min((math.dist(q, d) for d in door_pts), default=0.0))
    return [round(best[0], 4), round(best[1], 4)]


def _seg_dist(p: Vec, a: Vec, b: Vec) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy or 1.0
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


# ---------------------------------------------------------------- DXF reading


def convert_doc(doc, *, width: float | None = None, height: float | None = None, warn=None) -> dict[str, Any]:
    """Read an ezdxf drawing and return {"polygon", "doors", "name", "notes", "units", "dxf_size"} in metres."""
    warn = warn or (lambda msg: print(msg, file=sys.stderr))
    insunits = doc.header.get("$INSUNITS")
    k = unit_scale(insunits)
    msp = doc.modelspace()

    walls = [e for e in msp.query("LWPOLYLINE POLYLINE") if e.dxf.layer.upper() == "A-WALL"]
    if not walls:
        raise ConvertError("No room outline found: the DXF has no polyline on layer A-WALL.")
    wall = max(walls, key=lambda e: len(list(_poly_points(e))))
    outline = [(x * k, y * k) for x, y in _poly_points(wall)]
    loop, bridges = interior_loop(outline)
    raw_poly = loop

    arcs = [e for e in msp.query("ARC") if e.dxf.layer.upper() == "A-DOOR-SWNG"]
    hinges = [(a.dxf.center[0] * k, a.dxf.center[1] * k) for a in arcs]

    xs = [p[0] for p in raw_poly]
    ys = [p[1] for p in raw_poly]
    dxf_size = (max(xs) - min(xs), max(ys) - min(ys))
    if width is not None or height is not None:
        raw_poly, hinges = apply_overrides(raw_poly, hinges, width, height, warn)

    poly = normalize_polygon(raw_poly)
    doors = []
    for arc, hinge in zip(arcs, hinges):
        radius = arc.dxf.radius * k
        door = door_on_polygon(poly, hinge, radius, arc.dxf.start_angle, arc.dxf.end_angle)
        gap = next((math.dist(*br) for br in bridges
                    if min(math.dist(hinge, br[0]), math.dist(hinge, br[1])) <= ON_EDGE_TOL_M), None)
        if gap is not None and abs(gap - radius) > GAP_MISMATCH_WARN_M:
            warn(f"WARNING: a door is drawn {radius / IN:.1f} in wide but its wall gap is {gap / IN:.1f} in.")
        doors.append(door)

    texts = [((e.dxf.text if e.dxftype() == "TEXT" else e.plain_text()), (e.dxf.insert[0], e.dxf.insert[1]))
             for e in msp.query("TEXT MTEXT") if e.dxf.layer.upper() == "A-AREA-IDEN"]
    name, notes = room_name(texts)
    return {"polygon": poly, "doors": doors, "name": name, "notes": notes,
            "units": UNIT_NAMES[insunits], "dxf_size": dxf_size}


def _poly_points(e):
    if e.dxftype() == "LWPOLYLINE":
        for p in e.get_points("xy"):
            yield float(p[0]), float(p[1])
    else:
        for v in e.vertices:
            yield float(v.dxf.location[0]), float(v.dxf.location[1])


def convert_file(path: Path, **kw) -> dict[str, Any]:
    import ezdxf  # imported here so the pure geometry can be used without it

    try:
        doc = ezdxf.readfile(str(path))
    except (OSError, ezdxf.DXFError) as exc:
        raise ConvertError(f"Cannot read {path}: {exc}") from exc
    return convert_doc(doc, **kw)


# ---------------------------------------------------------------- floor plan update


def _r(v: float) -> float | int:
    v = round(v, 4)
    return int(v) if v == int(v) else v


def room_patch(conv: dict[str, Any]) -> dict[str, Any]:
    return {
        "polygon": [[_r(x), _r(y)] for x, y in conv["polygon"]],
        "doors": [{"edge": d["edge"], "offset": _r(d["offset"]), "width": _r(d["width"]), "swing": d["swing"],
                   "hinge": d["hinge"]} for d in conv["doors"]],
    }


def update_floorplan(plan: dict, room_id: str, conv: dict[str, Any], nodes: list[dict] | None,
                     links: list[dict] | None, source: str) -> dict:
    """Return a new floor plan with `room_id` replaced by the DXF room, its boards in it, and other
    rooms on that floor without boards marked simulated."""
    plan = json.loads(json.dumps(plan))  # deep copy, key order kept
    floor = next((f for f in plan["floors"] for r in f["rooms"] if r["id"] == room_id), None)
    if floor is None:
        raise ConvertError(f"Room {room_id!r} is not in the floor plan. Use --room-id with an existing room id.")
    patch = room_patch(conv)
    for room in floor["rooms"]:
        if room["id"] != room_id:
            continue
        if conv["name"]:
            room["name"] = conv["name"]
        room["simulated"] = False
        room["polygon"] = patch["polygon"]
        room["doors"] = patch["doors"]
        room["furniture"] = []
        cur = tuple(room["crewSlot"]) if isinstance(room.get("crewSlot"), list) else None
        room["crewSlot"] = crew_slot([tuple(p) for p in patch["polygon"]], patch["doors"], cur)
    if nodes is not None:
        plan["nodes"] = [{"id": n["id"], "role": n["role"], "room": room_id, "pos": n["pos"], "h": n["h"]} for n in nodes]
        plan["links"] = links or []
    rooms_with_nodes = {n["room"] for n in plan.get("nodes", [])}
    for room in floor["rooms"]:
        if room["id"] != room_id and room["id"] not in rooms_with_nodes:
            room["simulated"] = True
    plan["_source"] = source
    return plan


def validate_plan(plan: dict) -> list[str]:
    """Same rules as dashboard/src/floorplan/validate.ts."""
    errors = []
    floor_ids, room_ids, node_roles = set(), set(), {}
    for f in plan.get("floors", []):
        if f["id"] in floor_ids:
            errors.append(f"floor id {f['id']} duplicated")
        floor_ids.add(f["id"])
        for r in f["rooms"]:
            if r["id"] in room_ids:
                errors.append(f"room id {r['id']} duplicated")
            room_ids.add(r["id"])
            poly = [tuple(p) for p in r["polygon"]]
            if len(poly) < 3 or abs(signed_area(poly)) < EPS:
                errors.append(f"room {r['id']} polygon needs 3+ points and area")
                continue
            for d in r.get("doors", []):
                if not 0 <= d["edge"] < len(poly):
                    errors.append(f"room {r['id']} door edge {d['edge']} out of range")
                    continue
                L = math.dist(poly[d["edge"]], poly[(d["edge"] + 1) % len(poly)])
                if d["offset"] < 0 or d["width"] <= 0 or d["offset"] + d["width"] > L + 1e-6:
                    errors.append(f"room {r['id']} door does not fit edge {d['edge']}")
    for n in plan.get("nodes", []):
        if n["id"] in node_roles:
            errors.append(f"node id {n['id']} duplicated")
        node_roles[n["id"]] = n["role"]
        if n["room"] not in room_ids:
            errors.append(f"node {n['id']} room {n['room']} missing")
    for l in plan.get("links", []):
        if node_roles.get(l["tx"]) != "TX" or node_roles.get(l["rx"]) != "RX":
            errors.append(f"link {l['tx']} -> {l['rx']} does not join a TX to an RX")
    return errors


def dumps_plan(obj: Any, level: int = 0) -> str:
    """JSON in the floor plan file's style: 2-space indent, short arrays and objects on one line."""
    pad = "  " * level
    if isinstance(obj, (dict, list)) and _is_compact(obj):
        return _inline(obj)
    if isinstance(obj, dict):
        items = [f'{pad}  {json.dumps(k)}: {dumps_plan(v, level + 1)}' for k, v in obj.items()]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(obj, list):
        if not obj:
            return "[]"
        items = [f"{pad}  {dumps_plan(v, level + 1)}" for v in obj]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    return json.dumps(obj, ensure_ascii=False)


def _is_compact(obj: Any) -> bool:
    """Objects whose values hold no objects, and lists of such things, fit on one line if short."""
    if len(_inline(obj)) > 110:
        return False
    if isinstance(obj, dict):
        return all(not isinstance(v, dict) and (not isinstance(v, list) or _is_compact(v)) for v in obj.values())
    if isinstance(obj, list):
        return all(not isinstance(v, (dict, list)) or _is_compact(v) for v in obj)
    return True


def _inline(obj: Any) -> str:
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        return "{ " + ", ".join(f"{json.dumps(k)}: {_inline(v)}" for k, v in obj.items()) + " }"
    if isinstance(obj, list):
        return "[" + ", ".join(_inline(v) for v in obj) + "]"
    return json.dumps(obj, ensure_ascii=False)


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Convert a one-room DXF into the hub floor plan.")
    p.add_argument("dxf", type=Path)
    p.add_argument("--room-id", default="R1", help="floor plan room to replace (default R1)")
    p.add_argument("--width", help="override the room width, e.g. 13ft")
    p.add_argument("--height", help="override the room depth (y), e.g. 9ft4in")
    p.add_argument("--layout", type=Path, help="rs-view layout JSON with the board positions")
    p.add_argument("--write", type=Path, help="floor plan JSON to update in place")
    args = p.parse_args(argv)

    try:
        width = parse_length(args.width) if args.width else None
        height = parse_length(args.height) if args.height else None
        conv = convert_file(args.dxf, width=width, height=height)
        poly = conv["polygon"]
        room_wh = (max(x for x, _ in poly) - min(x for x, _ in poly), max(y for _, y in poly) - min(y for _, y in poly))
        nodes = links = None
        if args.layout:
            nodes, links = layout_nodes(json.loads(args.layout.read_text(encoding="utf-8")),
                                        warn=lambda m: print(m, file=sys.stderr), room_wh=room_wh)
        overrides = ", ".join(f"{k}={v}" for k, v in (("width", args.width), ("height", args.height)) if v) or "none"
        source = (f"Room {args.room_id} from {args.dxf.as_posix()} ({conv['units']}; DXF size "
                  f"{conv['dxf_size'][0]:.4f} x {conv['dxf_size'][1]:.4f} m; overrides: {overrides}"
                  + (f"; DXF area label {', '.join(conv['notes'])}" if conv["notes"] else "")
                  + (f"; boards from {args.layout.as_posix()}" if args.layout else "")
                  + f") by tools/dxf_to_floorplan.py on {SOURCE_DATE}.")
        if not args.write:
            out = {"name": conv["name"], **room_patch(conv)}
            if nodes is not None:
                out["nodes"], out["links"] = nodes, links
            print(dumps_plan(out))
            return 0
        plan = json.loads(args.write.read_text(encoding="utf-8"))
        new = update_floorplan(plan, args.room_id, conv, nodes, links, source)
        errors = validate_plan(new)
        if errors:
            raise ConvertError("The updated floor plan would be invalid: " + "; ".join(errors))
        args.write.write_text(dumps_plan(new) + "\n", encoding="utf-8")
        room = next(r for f in new["floors"] for r in f["rooms"] if r["id"] == args.room_id)
        print(f"Updated {args.write}: room {args.room_id} '{room['name']}'")
        print(dumps_plan({"room": room, "nodes": new["nodes"], "links": new["links"]}))
        return 0
    except ConvertError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
