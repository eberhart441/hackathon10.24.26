"""Example tests for the scripted incident State_Source (pwa-dashboard Req 21)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from hub.web.source import StateSource
from tools.mock_incident import ScriptedIncident, rank, rooms_from_floorplan, nodes_from_floorplan

PLAN = json.loads((Path(__file__).resolve().parents[2] / "hub" / "config" / "floorplan.json").read_text())

ROOM_STATES = {"MOTION", "POSSIBLE", "UNKNOWN", "NO_DETECTION"}
BANDS = {"high", "medium", "low"}
LABELS = {"MOTION": "MOTION", "POSSIBLE": "POSSIBLE", "UNKNOWN": "UNKNOWN", "NO_DETECTION": "NO DETECTION"}


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _opt(v, f) -> bool:
    return v is None or f(v)


def check_message(msg: dict) -> None:
    """Mirrors the required keys and enums in dashboard/src/ws/messages.ts parseMessage."""
    assert _num(msg["ts"])
    kind = msg["type"]
    if kind == "room_states":
        assert msg["system_state"] in {"IDLE", "CALIBRATION", "TEST", "ALARM_ACTIVE"}
        assert msg["simulated"] is True
        assert all(isinstance(x, str) for x in msg["ranking"])
        for r in msg["rooms"]:
            assert isinstance(r["room_id"], str)
            assert r["state"] in ROOM_STATES and r["label"] == LABELS[r["state"]]
            assert r["confidence_band"] in BANDS
            assert _num(r["confidence_pct"]) and 0 <= r["confidence_pct"] <= 100
            assert _opt(r["last_seen"], _num) and _opt(r["last_evidence"], _num)
            assert isinstance(r["stale"], bool)
            assert _opt(r["last_known_state"], lambda x: x in ROOM_STATES)
            assert _opt(r["stale_age_s"], _num)
            assert isinstance(r["calibrated"], bool) and isinstance(r["searched"], bool)
            assert _opt(r["annotation"], lambda x: x in {"responder_present", "recent_motion_may_be_responder"})
            assert _opt(r["alarm_time_state"], lambda x: x in ROOM_STATES)
            assert r["link_health"] in {"ok", "degraded", "offline"}
            assert r["source"] in {"edge", "hub"}
            assert _opt(r["model_ver"], _num)
    elif kind == "health":
        assert isinstance(msg["summary"], str)
        for n in msg["nodes"]:
            assert isinstance(n["node_id"], str) and isinstance(n["room_id"], str)
            assert n["role"] in {"TX", "RX"}
            assert n["status"] in {"ok", "degraded", "offline", "tx_dead"}
            for k in ("inferred_from", "cause", "action"):
                if k in n:
                    assert isinstance(n[k], str)
            if "measured_pps" in n:
                assert _num(n["measured_pps"])
        for f in msg["tag_faults"]:
            assert isinstance(f["tag_id"], str) and isinstance(f["last_room"], str) and _num(f["silent_s"])
    elif kind == "crew":
        for tag in msg["tags"]:
            assert isinstance(tag["tag_id"], str)
            assert tag["location_kind"] in {"room", "near", "between", "lost"}
            assert _opt(tag["room_id"], lambda x: isinstance(x, str))
            assert all(isinstance(x, str) for x in tag["near_rooms"])
            assert tag["confidence_band"] in BANDS
            assert _num(tag["last_heard_s"])
            assert tag["marker"] in {"solid", "hollow"}
            assert isinstance(tag["you_are_here"], bool)
        assert all(_num(v) for v in msg["floor_crew_counts"].values())
    elif kind == "recording":
        assert isinstance(msg["indicator"], str) and _num(msg["stored_samples"])
        assert _opt(msg["fault"], lambda x: isinstance(x, str))
    else:
        pytest.fail(f"unknown message type {kind!r}")
    text = json.dumps(msg).lower()
    assert not re.search(r"\b(empty|clear|safe)\b", text)
    assert not re.search(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", text)


@pytest.fixture
def setup():
    clock = FakeClock()
    src = ScriptedIncident(rooms_from_floorplan(PLAN), clock, nodes=nodes_from_floorplan(PLAN))
    return src, clock


def _by_type(msgs: list[dict]) -> dict[str, dict]:
    return {m["type"]: m for m in msgs}


def _room(msgs, rid):
    return next(r for r in _by_type(msgs)["room_states"]["rooms"] if r["room_id"] == rid)


def test_implements_state_source(setup):
    src, _ = setup
    assert isinstance(src, StateSource)
    assert src.room_ids() == {"R1", "R2"}


def test_idle_snapshot_has_no_rooms(setup):
    src, clock = setup
    msgs = _by_type(src.snapshot(clock()))
    assert set(msgs) == {"room_states", "health", "recording"}
    rs = msgs["room_states"]
    assert rs["system_state"] == "IDLE" and rs["rooms"] == [] and rs["ranking"] == []
    assert msgs["health"]["summary"] == "All sensors online"
    assert all(n["status"] == "ok" for n in msgs["health"]["nodes"])
    assert msgs["recording"]["indicator"] == "Not recording" and msgs["recording"]["stored_samples"] == 0


def test_after_trigger_r1_motion_ranked_first(setup):
    src, clock = setup
    assert src.trigger_alarm(clock()) == {"system_state": "ALARM_ACTIVE", "simulated": True}
    clock.t += 2
    msgs = src.snapshot(clock())
    rs = _by_type(msgs)["room_states"]
    assert rs["system_state"] == "ALARM_ACTIVE" and rs["simulated"] is True
    r1 = _room(msgs, "R1")
    assert r1["state"] == "MOTION" and r1["annotation"] == "responder_present"
    assert rs["ranking"][0] == "R1"
    assert _by_type(msgs)["recording"]["indicator"] == "Recording (alarm)"
    clock.t += 20  # t = 22
    assert _room(src.snapshot(clock()), "R1")["state"] == "POSSIBLE"


def test_r2_goes_unknown_stale_with_last_known_possible(setup):
    src, clock = setup
    src.trigger_alarm(clock())
    clock.t += 60
    msgs = src.snapshot(clock())
    r2 = _room(msgs, "R2")
    assert r2["state"] == "UNKNOWN" and r2["stale"] is True
    assert r2["last_known_state"] == "POSSIBLE" and r2["stale_age_s"] == pytest.approx(15.0)
    assert r2["alarm_time_state"] == "NO_DETECTION" and r2["link_health"] == "offline"
    health = _by_type(msgs)["health"]
    rx2 = next(n for n in health["nodes"] if n["node_id"] == "RX2")
    assert rx2["status"] == "offline"
    tag = _by_type(msgs)["crew"]["tags"][0]
    assert tag["marker"] == "hollow" and tag["last_heard_s"] >= 10
    clock.t += 5
    assert _room(src.snapshot(clock()), "R2")["stale_age_s"] == pytest.approx(20.0)


def test_mark_searched_moves_room_last(setup):
    src, clock = setup
    src.trigger_alarm(clock())
    clock.t += 2
    src.mark_searched("R1", clock())
    msgs = src.snapshot(clock())
    assert _by_type(msgs)["room_states"]["ranking"] == ["R2", "R1"]
    assert _room(msgs, "R1")["searched"] is True


def test_end_incident_returns_to_idle_and_clears_marks(setup):
    src, clock = setup
    src.trigger_alarm(clock())
    src.mark_searched("R1", clock())
    assert src.end_incident(clock()) == {"system_state": "IDLE"}
    assert _by_type(src.snapshot(clock()))["room_states"]["rooms"] == []
    src.trigger_alarm(clock())
    assert _room(src.snapshot(clock()), "R1")["searched"] is False


def test_every_snapshot_message_is_well_formed(setup):
    src, clock = setup
    for m in src.snapshot(clock()):
        check_message(m)
    start = clock()
    src.trigger_alarm(start)
    for t in range(0, 80):
        clock.t = start + t + 0.5
        for m in src.snapshot(clock()):
            check_message(m)


def test_simulated_floor2_rooms_from_plan():
    plan = json.loads(json.dumps(PLAN))
    plan["floors"].append({"id": "F2", "rooms": [
        {"id": rid, "simulated": True} for rid in ("R3", "R4", "R5")]})
    clock = FakeClock()
    src = ScriptedIncident(rooms_from_floorplan(plan), clock)
    src.trigger_alarm(clock())
    msgs = src.snapshot(clock())
    states = {r["room_id"]: r for r in _by_type(msgs)["room_states"]["rooms"]}
    assert states["R3"]["state"] == "POSSIBLE" and states["R4"]["state"] == "NO_DETECTION"
    assert states["R5"]["calibrated"] is False
    assert _by_type(msgs)["crew"]["floor_crew_counts"] == {"F1": 1, "F2": 0}
    for m in msgs:
        check_message(m)


def test_rank_orders_by_state_then_recency_searched_last():
    rooms = [
        {"room_id": "a", "state": "NO_DETECTION", "last_seen": None, "searched": False},
        {"room_id": "b", "state": "POSSIBLE", "last_seen": 10.0, "searched": False},
        {"room_id": "c", "state": "POSSIBLE", "last_seen": 20.0, "searched": False},
        {"room_id": "d", "state": "MOTION", "last_seen": 5.0, "searched": True},
        {"room_id": "e", "state": "UNKNOWN", "last_seen": None, "searched": False},
    ]
    assert rank(rooms) == ["c", "b", "e", "a", "d"]
