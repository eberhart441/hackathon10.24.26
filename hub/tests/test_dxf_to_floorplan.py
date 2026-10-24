"""tools/dxf_to_floorplan.py: the real conference-room DXF, overrides, layout conversion, and a
round-trip property on synthetic DXFs drawn the same way."""

import json
import math
import sys
from pathlib import Path

import ezdxf
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import dxf_to_floorplan as d2f  # noqa: E402

DXF = ROOT / "floor plans" / "conference_room.dxf"
LAYOUT = ROOT / "firmware" / "tools" / "layouts" / "demo-room.json"
MM = 0.001


def quiet(_msg):
    pass


def size(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return max(xs) - min(xs), max(ys) - min(ys)


def opening(poly, door):
    a, b = poly[door["edge"]], poly[(door["edge"] + 1) % len(poly)]
    L = math.dist(a, b)
    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    p = (a[0] + ux * door["offset"], a[1] + uy * door["offset"])
    q = (p[0] + ux * door["width"], p[1] + uy * door["width"])
    return p, q


# ---------------------------------------------------------------- the real DXF


def test_real_dxf_as_drawn():
    conv = d2f.convert_file(DXF, warn=quiet)
    w, h = size(conv["polygon"])
    assert w == pytest.approx(3.962, abs=MM)
    assert h == pytest.approx(2.896, abs=MM)
    assert conv["name"] == "Room 101"
    assert conv["units"] == "inches"
    assert any("SF" in n for n in conv["notes"])


def test_real_dxf_with_measured_height_and_door():
    warnings = []
    conv = d2f.convert_file(DXF, height=d2f.parse_length("9ft4in"), warn=warnings.append)
    poly = conv["polygon"]
    w, h = size(poly)
    assert w == pytest.approx(3.962, abs=MM)
    assert h == pytest.approx(2.845, abs=MM)
    assert d2f.signed_area(poly) > 0  # counter-clockwise
    assert poly[0] == (0.0, 0.0)  # starts bottom-left
    assert any("off by -2.0 in" in m for m in warnings)

    assert len(conv["doors"]) == 1
    door = conv["doors"][0]
    assert door["width"] == pytest.approx(0.813, abs=MM)
    assert door["swing"] == "in"
    p, q = opening(poly, door)
    assert p[0] == pytest.approx(0, abs=MM) and q[0] == pytest.approx(0, abs=MM)  # left wall
    lo, hi = sorted((p[1], q[1]))
    assert lo == pytest.approx(0.076, abs=MM)
    assert hi == pytest.approx(0.889, abs=MM)
    # Hinge is at the bottom of the opening (the arc centre in the DXF is (0, 3 in)).
    hinge = q if door["hinge"] == "end" else p
    assert hinge[1] == pytest.approx(0.0762, abs=MM)


def test_layout_conversion_matches_room_corners():
    nodes, links = d2f.layout_nodes(json.loads(LAYOUT.read_text(encoding="utf-8")))
    by_id = {n["id"]: n for n in nodes}
    assert by_id["TX1"]["pos"] == pytest.approx([0, 2.845], abs=3 * MM)
    rx3_tx = next(l["tx"] for l in links if l["rx"] == "RX3")
    assert by_id[rx3_tx]["pos"] == pytest.approx([3.962, 0], abs=3 * MM)
    assert {(l["tx"], l["rx"]) for l in links} == {("TX1", "RX1"), ("TX1", "RX2"), ("TX2", "RX3"), ("TX2", "RX4")}


# A two-floor plan in the shape the single-room converter was written for (the committed plan is
# now the walls-only drawing, written by tools/walls_to_floorplan.py).
TWO_FLOORS = {
    "schema": 1, "units": "m",
    "floors": [
        {"id": "F1", "name": "Floor 1", "rooms": [
            {"id": "R1", "name": "Old", "simulated": False, "polygon": [[0, 0], [3, 0], [3, 3], [0, 3]],
             "doors": [], "furniture": [{"kind": "desk", "x": 1, "y": 1, "w": 1, "d": 1}], "crewSlot": [1, 1]},
            {"id": "R2", "name": "Storage", "simulated": False, "polygon": [[4, 0], [7, 0], [7, 3], [4, 3]],
             "doors": [], "furniture": [], "crewSlot": [5, 1]}]},
        {"id": "F2", "name": "Floor 2", "rooms": [
            {"id": "R3", "name": "Office", "simulated": True, "polygon": [[0, 0], [3, 0], [3, 3], [0, 3]],
             "doors": [], "furniture": [], "crewSlot": [1, 1]}]},
    ],
    "nodes": [{"id": "RX9", "role": "RX", "room": "R2", "pos": [5, 1], "h": 1}],
    "links": [],
}


def test_update_floorplan_keeps_other_floors_and_validates():
    plan = json.loads(json.dumps(TWO_FLOORS))
    conv = d2f.convert_file(DXF, height=d2f.parse_length("9ft4in"), warn=quiet)
    nodes, links = d2f.layout_nodes(json.loads(LAYOUT.read_text(encoding="utf-8")))
    new = d2f.update_floorplan(plan, "R1", conv, nodes, links, "test")
    assert d2f.validate_plan(new) == []
    rooms = {r["id"]: r for f in new["floors"] for r in f["rooms"]}
    assert rooms["R1"]["name"] == "Room 101" and rooms["R1"]["simulated"] is False
    assert rooms["R1"]["furniture"] == []
    assert d2f.point_in_polygon(tuple(rooms["R1"]["crewSlot"]), [tuple(p) for p in rooms["R1"]["polygon"]])
    assert {n["room"] for n in new["nodes"]} == {"R1"}
    f2 = next(f for f in plan["floors"] if f["id"] == "F2")
    assert next(f for f in new["floors"] if f["id"] == "F2") == f2
    # R2 has no boards any more, so it is drawn as SIMULATED.
    assert rooms["R2"]["simulated"] is True
    # The written style round-trips as JSON.
    assert json.loads(d2f.dumps_plan(new)) == new


def test_unknown_room_and_units_are_explained():
    with pytest.raises(d2f.ConvertError, match="not in the floor plan"):
        d2f.update_floorplan({"floors": [{"id": "F1", "rooms": []}]}, "R1",
                             {"polygon": [(0, 0), (1, 0), (1, 1)], "doors": [], "name": None}, None, None, "x")
    with pytest.raises(d2f.ConvertError, match="drawing units"):
        d2f.unit_scale(0)


@pytest.mark.parametrize(
    "text, metres",
    [("9ft4in", 2.8448), ("112in", 2.8448), ("2.845m", 2.845), ("13ft", 3.9624), ("9' 4\"", 2.8448), ("284.5cm", 2.845)],
)
def test_parse_length(text, metres):
    assert d2f.parse_length(text) == pytest.approx(metres, abs=1e-6)


@pytest.mark.parametrize("text", ["", "nine feet", "12", "-3ft", "3 parsecs"])
def test_parse_length_rejects(text):
    with pytest.raises(d2f.ConvertError):
        d2f.parse_length(text)


# ---------------------------------------------------------------- property: synthetic DXFs


def synthetic_dxf(w, h, edge, start, width, hinge_at_start, t=4.5):
    """Draw a rectangle room the way the real file is drawn: one A-WALL polyline tracing the inner
    boundary from one side of the door gap round to the other, then the outer boundary back."""
    inner = [(0, 0), (0, h), (w, h), (w, 0)]  # clockwise round the room
    outer = [(-t, -t), (-t, h + t), (w + t, h + t), (w + t, -t)]
    a, b = inner[edge], inner[(edge + 1) % 4]
    L = math.dist(a, b)
    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    g0 = (a[0] + ux * start, a[1] + uy * start)
    g1 = (a[0] + ux * (start + width), a[1] + uy * (start + width))
    nx, ny = (-uy, ux)  # outward normal: a clockwise loop has the room on its right
    pts = [g1] + [inner[(edge + 1 + k) % 4] for k in range(4)] + [g0]
    pts += [(g0[0] + nx * t, g0[1] + ny * t)] + [outer[(edge - k) % 4] for k in range(4)]
    pts += [(g1[0] + nx * t, g1[1] + ny * t)]

    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 1
    msp = doc.modelspace()
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "A-WALL"})
    hinge, latch = (g0, g1) if hinge_at_start else (g1, g0)
    closed = math.atan2(latch[1] - hinge[1], latch[0] - hinge[0])
    inward = math.atan2(-ny, -nx)
    c, i = math.degrees(closed), math.degrees(inward)
    cross = math.cos(inward) * math.sin(closed) - math.sin(inward) * math.cos(closed)
    s, e = (i, c) if cross > 0 else (c, i)
    msp.add_arc(hinge, width, s, e, dxfattribs={"layer": "A-DOOR-SWNG"})
    msp.add_text("ROOM", dxfattribs={"layer": "A-AREA-IDEN", "insert": (w / 2, h / 2 + 4)})
    msp.add_text("7", dxfattribs={"layer": "A-AREA-IDEN", "insert": (w / 2, h / 2)})
    return doc, (g0, g1), hinge


@st.composite
def rooms(draw):
    w = draw(st.integers(60, 300))
    h = draw(st.integers(60, 300))
    edge = draw(st.integers(0, 3))
    L = h if edge % 2 == 0 else w
    width = draw(st.integers(24, min(40, L - 8)))
    start = draw(st.integers(3, L - width - 3))
    return w, h, edge, start, width, draw(st.booleans())


@settings(max_examples=120, deadline=None)
@given(rooms())
def test_synthetic_dxf_round_trips(room):
    w, h, edge, start, width, hinge_at_start = room
    doc, (g0, g1), hinge = synthetic_dxf(w, h, edge, start, width, hinge_at_start)
    conv = d2f.convert_doc(doc, warn=quiet)
    poly = conv["polygon"]
    k = 0.0254
    expected = [(0, 0), (w * k, 0), (w * k, h * k), (0, h * k)]
    assert len(poly) == 4
    for p, q in zip(poly, expected):
        assert p == pytest.approx(q, abs=MM)
    assert conv["name"] == "Room 7"
    (door,) = conv["doors"]
    assert door["swing"] == "in"
    assert door["width"] == pytest.approx(width * k, abs=MM)
    p, q = opening(poly, door)
    got = sorted([p, q])
    want = sorted([(g0[0] * k, g0[1] * k), (g1[0] * k, g1[1] * k)])
    for a, b in zip(got, want):
        assert a == pytest.approx(b, abs=MM)
    drawn_hinge = q if door["hinge"] == "end" else p
    assert drawn_hinge == pytest.approx((hinge[0] * k, hinge[1] * k), abs=MM)


@settings(max_examples=100, deadline=None)
@given(st.lists(st.tuples(st.floats(-50, 50), st.floats(-50, 50)), min_size=3, max_size=8))
def test_normalize_is_ccw_and_starts_bottom_left(points):
    try:
        poly = d2f.normalize_polygon(points)
    except d2f.ConvertError:
        return  # degenerate input is refused, not mangled
    assert d2f.signed_area(poly) > 0
    lowest = min(round(p[1], 9) for p in poly)
    assert round(poly[0][1], 9) == lowest
