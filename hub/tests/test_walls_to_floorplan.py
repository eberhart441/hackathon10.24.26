"""tools/walls_to_floorplan.py and the committed floor plan it writes: the walls are the walls-only
DXF's, every room sits in the open space the walls leave, every door is a real gap, and every board
counts for the room it stands in."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import dxf_to_floorplan as d2f  # noqa: E402
import walls_to_floorplan as w2f  # noqa: E402
from roomsense_hub.dxf_walls import read_dxf_text  # noqa: E402

from hub.live_source import FloorplanLinks  # noqa: E402

DXF = ROOT / "floor plans" / "walls_only.dxf"
LAYOUT = ROOT / "firmware" / "tools" / "layouts" / "two-rooms.json"
LAYOUT_ORIGIN = (0, -4.5)  # Room 1's top-left inside corner, DXF inches
FLOORPLAN = ROOT / "hub" / "config" / "floorplan.json"
TWO_ROOMS = ROOT / "hub" / "config-two-rooms" / "floorplan.json"
NUDGE = 0.05


@pytest.fixture(scope="module")
def plan():
    return json.loads(FLOORPLAN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def floor(plan):
    return plan["floors"][0]


def dxf_lines():
    return read_dxf_text(DXF.read_text(encoding="utf-8", errors="replace"))


def is_open(p, walls):
    """Even-odd, as the dashboard fills the walls: inside an odd number of loops is wall."""
    n = sum(d2f.point_in_polygon(p, [tuple(q) for q in loop]) for loop in walls)
    return n > 0 and n % 2 == 0


def test_committed_walls_are_the_dxf_walls(plan, floor):
    lines, units = dxf_lines()
    assert units == 1  # inches
    assert floor["walls"] == w2f.walls_m(lines, d2f.unit_scale(units), w2f.wall_frame(lines))
    assert d2f.validate_plan(plan) == []


def test_the_plan_is_only_the_walls_only_drawing(plan):
    assert [f["id"] for f in plan["floors"]] == ["F1"]
    rooms = {r["id"]: r for r in plan["floors"][0]["rooms"]}
    assert set(rooms) == {"R1", "R2", "HALL"}
    assert not any(r.get("simulated") for r in rooms.values())
    # The two-room demo (tools/live_hub.py --floorplan hub/config-two-rooms/floorplan.json) shows the same plan.
    assert json.loads(TWO_ROOMS.read_text(encoding="utf-8")) == plan


def test_every_room_sits_in_open_space(floor):
    for r in floor["rooms"]:
        poly = [tuple(p) for p in r["polygon"]]
        assert d2f.signed_area(poly) > 0, r["id"]  # counter-clockwise
        for x, y in poly:  # each corner, nudged 1 cm into the room, is floor, not wall
            inside = [(x + sx, y + sy) for sx in (-0.01, 0.01) for sy in (-0.01, 0.01)
                      if d2f.point_in_polygon((x + sx, y + sy), poly)]
            assert inside and all(is_open(q, floor["walls"]) for q in inside), (r["id"], x, y)
        assert is_open(tuple(r["crewSlot"]), floor["walls"]) and d2f.point_in_polygon(tuple(r["crewSlot"]), poly)


def test_every_door_is_a_gap_in_the_wall_and_the_wall_beside_it_is_solid(floor):
    for r in floor["rooms"]:
        poly = [tuple(p) for p in r["polygon"]]
        for d in r["doors"]:
            a, b = poly[d["edge"]], poly[(d["edge"] + 1) % len(poly)]
            L = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            ox, oy = uy, -ux  # right of a counter-clockwise edge = outside the room

            def at(t):
                return (a[0] + ux * t + ox * NUDGE, a[1] + uy * t + oy * NUDGE)

            for t in (d["offset"] + 0.05, d["offset"] + d["width"] / 2, d["offset"] + d["width"] - 0.05):
                assert is_open(at(t), floor["walls"]), (r["id"], d)
            assert not is_open(at(d["offset"] - 0.03), floor["walls"]), (r["id"], d)
            assert not is_open(at(d["offset"] + d["width"] + 0.03), floor["walls"]), (r["id"], d)


def test_boards_count_for_the_room_they_stand_in(plan):
    rooms = {n["id"]: n["room"] for n in plan["nodes"]}
    assert rooms == {"TX1": "HALL", "RX1": "HALL", "RX2": "R1", "RX3": "R1"}
    assert {(l["tx"], l["rx"]) for l in plan["links"]} == {("TX1", f"RX{i}") for i in range(1, 4)}
    links = FloorplanLinks(plan)
    assert links.live_rooms == ["R1", "HALL"] and links.unsensed == ["R2"]


def test_layout_conversion_matches_the_layout_file(plan):
    lines, units = dxf_lines()
    nodes, _ = w2f.layout_boards(json.loads(LAYOUT.read_text(encoding="utf-8")), LAYOUT_ORIGIN,
                                 d2f.unit_scale(units), w2f.wall_frame(lines))
    by_id = {n["id"]: n for n in nodes}
    # RX2 is 12.697 ft right of and 0.576 ft down from Room 1's top-left inside corner.
    r1 = next(r for r in plan["floors"][0]["rooms"] if r["id"] == "R1")
    left, top = min(x for x, _ in r1["polygon"]), max(y for _, y in r1["polygon"])
    assert by_id["RX2"]["pos"] == pytest.approx([left + 12.697 * d2f.FT, top - 0.576 * d2f.FT], abs=1e-3)
    assert [n["pos"] for n in plan["nodes"]] == [n["pos"] for n in nodes]


def test_a_board_in_no_room_goes_to_the_nearest_with_a_warning(floor):
    said = []
    assert w2f.room_of((7.75, 7.0), floor["rooms"], said.append) == "R1"  # inside Room 1's right wall
    assert said and "nearest, R1" in said[0]
