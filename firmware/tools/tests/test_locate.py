"""The motion location estimate, with made-up link scores (no hardware)."""
import json
import math

from beacon_hub.locate import Layout, Link, Locator, link_score, link_weight, load_layout
from beacon_hub.viewer import DEFAULT_LAYOUT, Hub

# Two links crossing in an X over a 10 x 10 ft room; they meet in the middle.
X = Layout((10.0, 10.0), (Link("A", (0, 0), (10, 10)), Link("B", (10, 0), (0, 10))))


def test_a_link_is_most_sensitive_on_its_line():
    link = X.links[0]
    assert link_weight(link, 5, 5) > 0.99
    assert link_weight(link, 5, 5) > link_weight(link, 6, 4) > link_weight(link, 8, 2)
    assert link_weight(link, 10, 0) < 0.01


def test_unjudgeable_links_have_no_score():
    assert link_score("weak", 1.0, 0.5, 1.3) is None
    assert link_score("warming", None, None, None) is None
    assert link_score("quiet", 0.5, 0.5, 1.3) == 0.0
    assert link_score("motion", 1.3, 0.5, 1.3) == 1.0


def test_two_disturbed_links_place_motion_where_they_cross():
    loc = Locator(X).update({"A": 2.0, "B": 2.0})
    assert loc["moving"]
    assert math.dist((loc["x"], loc["y"]), (5, 5)) < 1.0


def test_a_quiet_link_pushes_the_estimate_away_from_itself():
    loc = Locator(X).update({"A": 2.0, "B": 0.0})
    assert loc["moving"]
    # on link A (y == x), away from the crossing
    assert abs(loc["x"] - loc["y"]) < 1.5
    assert math.dist((loc["x"], loc["y"]), (5, 5)) > 2.0


def test_no_motion_means_no_estimate_but_the_last_place_is_kept():
    locator = Locator(X)
    locator.update({"A": 2.0, "B": 2.0})
    loc = locator.update({"A": 0.0, "B": 0.0})
    assert not loc["moving"] and loc["x"] is None
    assert loc["last"] is not None


def test_unknown_links_are_ignored_not_treated_as_quiet():
    loc = Locator(X).update({"A": 2.0, "B": None})
    # One working link alone cannot say where along it the motion is, so it is reported, not placed.
    assert loc["moving"] is False
    assert loc["motion_seen"] is True
    assert loc["excluded"] == {"B": "not reporting"}
    assert "cannot be placed" in loc["note"]


def test_bundled_layout_loads_and_the_hub_reports_a_location():
    layout = load_layout(DEFAULT_LAYOUT)
    assert {l.rx_id for l in layout.links} == {"RX1", "RX2", "RX3", "RX4"}
    m = json.loads(Hub(layout).snapshot_json(0.0))
    assert m["layout"]["room"] == [13.0, 9.33]
    assert m["location"]["moving"] is False
    assert all(v is None for v in m["location"]["scores"].values())


def test_without_a_layout_the_hub_message_is_unchanged():
    m = json.loads(Hub().snapshot_json(0.0))
    assert "layout" not in m and "location" not in m


# --- floor-plan walls and the conference-room layout ---------------------------------------------

def test_dxf_walls_convert_inches_to_room_feet_with_y_down(tmp_path):
    from beacon_hub.dxf_walls import read_dxf_lines, to_layout

    dxf = tmp_path / "plan.dxf"
    dxf.write_text("\n".join([
        "0", "SECTION", "2", "ENTITIES",
        "0", "LWPOLYLINE", "70", "1", "10", "0", "20", "0", "10", "156", "20", "0", "10", "156", "20", "114",
        "0", "LINE", "10", "0", "20", "114", "11", "-24", "21", "114",
        "0", "ENDSEC", "0", "EOF"]) + "\n", encoding="utf-8")
    lines = to_layout(read_dxf_lines(dxf), (0.0, 114.0), 12.0)
    assert lines[0] == [(0.0, 9.5), (13.0, 9.5), (13.0, 0.0), (0.0, 9.5)]  # closed: first point repeated
    assert lines[1] == [(0.0, 0.0), (-2.0, 0.0)]


def test_the_conference_room_layout_loads_with_walls_and_boards_where_marked():
    from pathlib import Path

    from beacon_hub.locate import load_layout

    lay = load_layout(Path(__file__).resolve().parent.parent / "layouts" / "conference-room.json")
    assert lay.room == (13.0, 9.5)
    links = {l.rx_id: l for l in lay.links}
    assert set(links) == {"RX1", "RX2", "RX3", "RX4"}
    assert len({l.tx for l in lay.links}) == 1  # one transmitter, TX1
    assert links["RX4"].rx == links["RX4"].tx  # RX4 stands next to TX1
    assert links["RX1"].tx[0] < 0  # TX1 is out in the hallway
    for rx in ("RX1", "RX2", "RX3"):  # these three are inside the room
        x, y = links[rx].rx
        assert 0 <= x <= 13 and 0 <= y <= 9.5
    assert lay.walls and lay.to_json()["walls"]


def test_a_receiver_on_top_of_its_transmitter_never_pulls_the_estimate_into_the_room():
    from pathlib import Path

    from beacon_hub.locate import Locator, load_layout

    lay = load_layout(Path(__file__).resolve().parent.parent / "layouts" / "conference-room.json")
    out = Locator(lay).update({"RX1": 0.0, "RX2": 0.0, "RX3": 0.0, "RX4": 3.0})
    assert out["moving"] is False  # only the hallway pair is disturbed: nothing to place inside the room


# --- a receiver that is obviously off changes the location estimate ------------------------------

THREE = Layout((10.0, 10.0), (Link("A", (0, 0), (10, 10)), Link("B", (10, 0), (0, 10)), Link("C", (0, 5), (10, 5))))


def test_an_excluded_quiet_link_no_longer_pushes_the_estimate_away():
    healthy = Locator(THREE).update({"A": 2.0, "B": 2.0, "C": 0.0})
    off = Locator(THREE).update({"A": 2.0, "B": 2.0, "C": 0.0}, {"C": "losing packets (12/s)"})
    assert healthy["moving"] and off["moving"]
    assert off["excluded"] == {"C": "losing packets (12/s)"}
    assert off["degraded"] is True and "C left out" in off["note"]
    assert off["spread"] > healthy["spread"]  # fewer working links, wider zone


def test_cells_only_an_excluded_link_could_see_are_marked_unseen():
    loc = Locator(THREE).update({"A": 0.0, "B": 0.0, "C": 0.0}, {"A": "offline: no heartbeat for 10 s"})
    covered = loc["grid"]["covered"]
    assert not all(covered) and any(covered)


def test_motion_on_an_excluded_link_is_still_reported_never_dropped():
    loc = Locator(THREE).update({"A": 0.0, "B": 0.0, "C": 2.5}, {"C": "glitching (40 bad packets in 10 s)"})
    assert loc["moving"] is False
    assert loc["motion_seen"] is True
    assert "C shows motion but is unreliable" in loc["note"]


def test_too_few_working_links_reports_motion_without_a_position():
    loc = Locator(THREE).update({"A": 2.0, "B": None, "C": None}, {"C": "weak or blocked signal"})
    assert loc["moving"] is False and loc["motion_seen"] is True
    assert loc["excluded"] == {"B": "not reporting", "C": "weak or blocked signal"}
