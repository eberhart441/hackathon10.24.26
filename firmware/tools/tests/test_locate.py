"""The motion location estimate, with made-up link scores (no hardware)."""
import json
import math

from roomsense_hub.locate import Layout, Link, Locator, link_score, link_weight, load_layout
from roomsense_hub.viewer import DEFAULT_LAYOUT, Hub

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
    assert loc["moving"]
    assert abs(loc["x"] - loc["y"]) < 1.5  # somewhere on link A; one link alone cannot say where along it


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
