"""Property tests on the scripted incident and ranking (pure functions)."""

import json
import re

from hypothesis import given, settings
from hypothesis import strategies as st

from hub import scripted

MAC = re.compile(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", re.IGNORECASE)
BANNED = re.compile(r"\b(empty|clear(ed)?|safe)\b", re.IGNORECASE)
STATES = list(scripted.PRIORITY)

room_view = st.fixed_dictionaries({
    "room_id": st.sampled_from(["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]),
    "state": st.sampled_from(STATES),
    "searched": st.booleans(),
    "last_seen": st.one_of(st.none(), st.floats(min_value=0, max_value=2e9, allow_nan=False)),
})


@settings(max_examples=200)
@given(st.lists(room_view, max_size=8, unique_by=lambda r: r["room_id"]))
def test_ranking_order(rooms):
    order = scripted.rank(rooms)
    by_id = {r["room_id"]: r for r in rooms}
    ranked = [by_id[i] for i in order]
    assert sorted(order) == sorted(by_id)
    for a, b in zip(ranked, ranked[1:]):
        if a["searched"] != b["searched"]:
            assert not a["searched"]  # searched rooms last
        else:
            pa, pb = scripted.PRIORITY[a["state"]], scripted.PRIORITY[b["state"]]
            assert pa <= pb
            if pa == pb:
                assert (a["last_seen"] or 0) >= (b["last_seen"] or 0)
    for group in (True, False):
        g = [r for r in ranked if r["searched"] == group]
        unk = [i for i, r in enumerate(g) if r["state"] == "UNKNOWN"]
        nod = [i for i, r in enumerate(g) if r["state"] == "NO_DETECTION"]
        if unk and nod:
            assert max(unk) < min(nod)


@settings(max_examples=150)
@given(
    vt=st.floats(min_value=0, max_value=200, allow_nan=False),
    speed=st.sampled_from([0.5, 1.0, 4.0]),
    searched=st.sets(st.sampled_from(scripted.ROOM_IDS)),
)
def test_frames_have_no_mac_or_banned_words_and_valid_shapes(vt, speed, searched):
    c = scripted.Clock(1_730_000_000.0, speed)
    frame = scripted.build_frame(vt, c, searched, scripted.alarm_snapshot(c))
    text = json.dumps(frame)
    assert not MAC.search(text)
    assert not BANNED.search(text)
    rs = frame["room_states"]
    assert rs["simulated"] is True and rs["system_state"] == "ALARM_ACTIVE"
    assert rs["ranking"] == scripted.rank(rs["rooms"])
    for r in rs["rooms"]:
        assert r["state"] in scripted.PRIORITY and r["label"] == scripted.LABELS[r["state"]]
        assert 0 <= r["confidence_pct"] <= 100 and r["confidence_band"] == scripted.band(r["confidence_pct"])
        assert r["searched"] == (r["room_id"] in searched)
        assert r["alarm_time_state"] in scripted.PRIORITY
        if r["stale"]:
            assert r["state"] == "UNKNOWN" and r["last_known_state"] and r["stale_age_s"] >= 0
    for tag in frame["crew"]["tags"]:
        if tag["confidence_band"] == "low":
            assert tag["location_kind"] != "room"  # low confidence never resolves to one room
        if tag["location_kind"] == "lost":
            assert tag["marker"] == "hollow" and tag["last_heard_s"] >= scripted.TAG_LOST_S
    assert {t["type"] for t in frame.values()} == {"room_states", "health", "crew", "recording"}


@settings(max_examples=100)
@given(now=st.floats(min_value=0, max_value=2e9, allow_nan=False))
def test_idle_frame_has_no_occupancy(now):
    f = scripted.idle_frame(now)
    assert f["room_states"]["rooms"] == [] and f["room_states"]["ranking"] == []
    assert f["crew"]["tags"] == [] and f["recording"]["stored_samples"] == 0
    assert f["recording"]["indicator"] == "Not recording"
    assert not BANNED.search(json.dumps(f)) and not MAC.search(json.dumps(f))


def test_timeline_milestones():
    c = scripted.Clock(1_730_000_000.0, 1.0)
    snap = scripted.alarm_snapshot(c)
    at = lambda vt: {r["room_id"]: r for r in scripted.build_frame(vt, c, set(), snap)["room_states"]["rooms"]}
    assert at(5)["R1"]["state"] == "MOTION" and at(5)["R1"]["annotation"] == "responder_present"
    assert at(30)["R1"]["state"] == "POSSIBLE"
    r2 = at(50)["R2"]
    assert r2["state"] == "UNKNOWN" and r2["stale"] and r2["last_known_state"] == "POSSIBLE" and r2["stale_age_s"] == 18
    assert at(50)["R2"]["alarm_time_state"] == "POSSIBLE"
    assert at(5)["R5"]["calibrated"] is False
    health = scripted.build_frame(50, c, set(), snap)["health"]
    assert next(n for n in health["nodes"] if n["node_id"] == "RX2")["status"] == "offline"
    late = scripted.build_frame(95, c, set(), snap)
    assert late["crew"]["tags"][0]["marker"] == "hollow"
    assert late["health"]["tag_faults"][0]["tag_id"] == "E1"
