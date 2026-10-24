"""Responder tag location: the parent design's room-level rules (Req 25, 30), injected clock."""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from hub.tag_locator import LEAD_HOLD_S, LOST_S, TagLocator

ROOMS = ["R1", "R2", "R3"]


def feed(loc, t, **rssi_by_room):
    for room, rssi in rssi_by_room.items():
        loc.on_summary("E1", room, rssi, t)


# Generation speed depends on machine load, not on the property; never fail on it.
@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(st.tuples(st.dictionaries(st.sampled_from(ROOMS), st.floats(-100, -30), max_size=3),
                          st.floats(0.1, 4.0)), min_size=1, max_size=40))
def test_low_confidence_is_never_a_single_room(steps):
    loc = TagLocator(ROOMS)
    t = 0.0
    for heard, gap in steps:
        for room, rssi in heard.items():
            loc.on_summary("E1", room, rssi, t)
        if "E1" in loc.tags:
            tag = loc.locate("E1", t)
            assert tag["location_kind"] in ("room", "near", "between", "lost")
            if tag["confidence_band"] == "low":
                assert tag["location_kind"] != "room"
            if tag["location_kind"] == "room":
                assert tag["room_id"] in ROOMS and tag["near_rooms"] == []
        t += gap


def test_a_tag_heard_by_one_room_is_located_there_with_high_confidence():
    loc = TagLocator(ROOMS)
    feed(loc, 0.0, R1=-60)
    tag = loc.locate("E1", 0.5)
    assert (tag["location_kind"], tag["room_id"], tag["confidence_band"]) == ("room", "R1", "high")


def test_switching_rooms_needs_a_six_db_lead_held_for_two_seconds():
    loc = TagLocator(ROOMS)
    t = 0.0
    for _ in range(3):
        feed(loc, t, R1=-55, R2=-80)
        loc.locate("E1", t)
        t += 1
    # R2 now leads by ~8 dB, but only for 1 s: still R1 (shown as low-confidence "near", not R2)
    feed(loc, t, R1=-70, R2=-62)
    first = loc.locate("E1", t)
    assert first["room_id"] != "R2"
    for _ in range(4):
        t += 1
        feed(loc, t, R1=-75, R2=-55)
        last = loc.locate("E1", t)
    assert last["room_id"] == "R2" and last["location_kind"] == "room"
    assert t - 3 >= LEAD_HOLD_S


def test_close_signals_from_two_rooms_read_between_rooms():
    loc = TagLocator(ROOMS)
    feed(loc, 0.0, R1=-70, R2=-72)
    tag = loc.locate("E1", 0.2)
    assert tag["location_kind"] == "between" and set(tag["near_rooms"]) == {"R1", "R2"}


def test_a_silent_tag_becomes_a_hollow_marker_at_its_last_room_and_a_fault():
    loc = TagLocator(ROOMS)
    feed(loc, 0.0, R2=-58)
    loc.locate("E1", 0.5)
    tag = loc.locate("E1", LOST_S + 1)
    assert (tag["location_kind"], tag["room_id"], tag["marker"]) == ("lost", "R2", "hollow")
    assert loc.lost_faults(LOST_S + 1) == [{"tag_id": "E1", "last_room": "R2", "silent_s": 11}]


def test_a_degraded_room_or_offline_receiver_with_weak_signal_forces_low():
    loc = TagLocator(ROOMS)
    feed(loc, 0.0, R1=-60)
    assert loc.locate("E1", 0.2, degraded_rooms={"R1"})["confidence_band"] == "low"
    loc2 = TagLocator(ROOMS)
    feed(loc2, 0.0, R1=-80)
    assert loc2.locate("E1", 0.2, any_rx_offline=True)["location_kind"] != "room"


def test_crew_counts_only_count_a_certain_floor():
    loc = TagLocator(ROOMS)
    feed(loc, 0.0, R1=-60)
    msg = loc.crew_message(0.5, {"R1": "F1", "R2": "F1", "R3": "F2"})
    assert msg["floor_crew_counts"] == {"F1": 1}
    assert msg["tags"][0]["tag_id"] == "E1"


def test_a_single_room_building_locates_without_a_competitor():
    loc = TagLocator(["R1"])
    feed(loc, 0.0, R1=-70)
    tag = loc.locate("E1", 0.5)
    assert (tag["location_kind"], tag["room_id"], tag["confidence_band"]) == ("room", "R1", "high")
