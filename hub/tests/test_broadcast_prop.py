"""Property test for wire redaction and MAC-free broadcasts (design Property 25, Req 14.1, 6.7).

Feature: pwa-dashboard, Property 25: Broadcasts carry no occupancy in IDLE and no MAC-like strings
"""

from __future__ import annotations

import copy
import json
import re

from hypothesis import given, settings
from hypothesis import strategies as st

from hub.web.broadcast import Broadcaster, redact_for_wire

MAC_RE = re.compile(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", re.IGNORECASE)

SYSTEM_STATES = ["IDLE", "CALIBRATION", "TEST", "ALARM_ACTIVE"]
ROOM_STATES = ["MOTION", "POSSIBLE", "UNKNOWN", "NO_DETECTION"]
LABELS = {"MOTION": "MOTION", "POSSIBLE": "POSSIBLE", "UNKNOWN": "UNKNOWN", "NO_DETECTION": "NO DETECTION"}
BANDS = ["high", "medium", "low"]
WORDS = ["kitchen", "hall", "stairs", "ok", "check", "power", "antenna", "rec", "REC", "silent", "move"]

# --- realistic id / text alphabets ----------------------------------------
room_id = st.integers(1, 12).map(lambda n: f"R{n}")
node_id = st.builds(lambda p, n: f"{p}{n}", st.sampled_from(["TX", "RX"]), st.integers(1, 12))
tag_id = st.integers(1, 9).map(lambda n: f"E{n}")
floor_id = st.integers(1, 4).map(lambda n: f"F{n}")
text = st.lists(st.sampled_from(WORDS), min_size=0, max_size=6).map(" ".join)
ts = st.floats(min_value=0, max_value=2e9, allow_nan=False, allow_infinity=False)
opt_ts = st.none() | ts
pct = st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False)
opt_state = st.none() | st.sampled_from(ROOM_STATES)


@st.composite
def room_entry(draw) -> dict:
    state = draw(st.sampled_from(ROOM_STATES))
    return {
        "room_id": draw(room_id),
        "state": state,
        "label": LABELS[state],
        "confidence_band": draw(st.sampled_from(BANDS)),
        "confidence_pct": draw(pct),
        "last_seen": draw(opt_ts),
        "last_evidence": draw(opt_ts),
        "stale": draw(st.booleans()),
        "last_known_state": draw(opt_state),
        "stale_age_s": draw(st.none() | pct),
        "calibrated": draw(st.booleans()),
        "searched": draw(st.booleans()),
        "annotation": draw(st.sampled_from([None, "responder_present", "recent_motion_may_be_responder"])),
        "alarm_time_state": draw(opt_state),
        "link_health": draw(st.sampled_from(["ok", "degraded", "offline"])),
        "source": draw(st.sampled_from(["edge", "hub"])),
        "model_ver": draw(st.none() | st.integers(0, 50)),
    }


@st.composite
def room_states_msg(draw, system_state=st.sampled_from(SYSTEM_STATES)) -> dict:
    rooms = draw(st.lists(room_entry(), max_size=6))
    return {
        "type": "room_states",
        "ts": draw(ts),
        "system_state": draw(system_state),
        "simulated": draw(st.booleans()),
        "rooms": rooms,
        "ranking": [r["room_id"] for r in rooms],
    }


@st.composite
def health_node(draw) -> dict:
    node = {
        "node_id": draw(node_id),
        "role": draw(st.sampled_from(["TX", "RX"])),
        "room_id": draw(room_id),
        "status": draw(st.sampled_from(["ok", "degraded", "offline", "tx_dead"])),
    }
    if draw(st.booleans()):
        node["measured_pps"] = draw(pct)
    if draw(st.booleans()):
        node["inferred_from"] = draw(node_id)
    if draw(st.booleans()):
        node["cause"] = draw(text)
    if draw(st.booleans()):
        node["action"] = draw(text)
    return node


health_msg = st.builds(
    lambda t, s, n, f: {"type": "health", "ts": t, "summary": s, "nodes": n, "tag_faults": f},
    ts,
    text,
    st.lists(health_node(), max_size=6),
    st.lists(st.fixed_dictionaries({"tag_id": tag_id, "last_room": room_id, "silent_s": pct}), max_size=3),
)


@st.composite
def crew_tag(draw) -> dict:
    return {
        "tag_id": draw(tag_id),
        "location_kind": draw(st.sampled_from(["room", "near", "between", "lost"])),
        "room_id": draw(st.none() | room_id),
        "near_rooms": draw(st.lists(room_id, max_size=3)),
        "confidence_band": draw(st.sampled_from(BANDS)),
        "last_heard_s": draw(pct),
        "marker": draw(st.sampled_from(["solid", "hollow"])),
        "you_are_here": draw(st.booleans()),
    }


crew_msg = st.builds(
    lambda t, tags, counts: {"type": "crew", "ts": t, "tags": tags, "floor_crew_counts": counts},
    ts,
    st.lists(crew_tag(), max_size=5),
    st.dictionaries(floor_id, st.integers(0, 9), max_size=4),
)

recording_msg = st.builds(
    lambda t, i, n, f: {"type": "recording", "ts": t, "indicator": i, "stored_samples": n, "fault": f},
    ts,
    text,
    st.integers(0, 10**6),
    st.none() | text,
)

any_msg = st.one_of(room_states_msg(), health_msg, crew_msg, recording_msg)


@st.composite
def snapshot(draw) -> list[dict]:
    """A StateSource snapshot: at most one message of each type, in any order."""
    picked = [
        m
        for m in (
            draw(st.none() | room_states_msg()),
            draw(health_msg),  # health is in every snapshot (Req 7.7)
            draw(st.none() | crew_msg),
            draw(st.none() | recording_msg),
        )
        if m is not None
    ]
    return draw(st.permutations(picked))


class FakeSource:
    """StateSource that replays a scripted list of snapshots, one per call."""

    def __init__(self, snapshots: list[list[dict]]) -> None:
        self._snapshots = list(snapshots)
        self.calls = 0

    def room_ids(self) -> set[str]:
        return {r["room_id"] for snap in self._snapshots for m in snap for r in m.get("rooms", [])}

    def snapshot(self, now: float) -> list[dict]:
        snap = self._snapshots[self.calls]
        self.calls += 1
        return snap

    def trigger_alarm(self, now: float) -> dict:
        return {"system_state": "ALARM_ACTIVE", "simulated": True}

    def end_incident(self, now: float) -> dict:
        return {"system_state": "IDLE"}

    def mark_searched(self, room_id: str, now: float) -> None:
        pass


# Feature: pwa-dashboard, Property 25: Broadcasts carry no occupancy in IDLE and no MAC-like strings
@settings(max_examples=200, deadline=None)
@given(any_msg, st.none() | st.sampled_from(SYSTEM_STATES))
def test_redact_for_wire(msg: dict, system_state: str | None) -> None:
    """**Validates: Requirements 14.1, 6.7**"""
    before = copy.deepcopy(msg)
    out = redact_for_wire(msg, system_state)

    assert msg == before, "redact_for_wire mutated its input"

    if msg["type"] == "room_states" and msg["system_state"] == "IDLE":
        assert out["rooms"] == [] and out["ranking"] == []
        assert {k: v for k, v in out.items() if k not in ("rooms", "ranking")} == {
            k: v for k, v in msg.items() if k not in ("rooms", "ranking")
        }
    elif msg["type"] == "crew" and system_state == "IDLE":
        assert out["tags"] == []
    else:
        assert out == msg


# Feature: pwa-dashboard, Property 25: Broadcasts carry no occupancy in IDLE and no MAC-like strings
@settings(max_examples=200, deadline=None)
@given(st.lists(snapshot(), min_size=1, max_size=5))
def test_broadcaster_wire_frames(snapshots: list[list[dict]]) -> None:
    """**Validates: Requirements 14.1, 6.7**

    Across a sequence of snapshots the Broadcaster tracks the system state from
    the latest room_states (starting IDLE; a snapshot's own room_states applies
    to the whole snapshot), so crew is redacted whenever the system is IDLE;
    no frame carries a MAC-like string.
    """
    originals = copy.deepcopy(snapshots)
    b = Broadcaster(FakeSource(snapshots))
    state = "IDLE"  # reference model of the tracked system state

    for i, snap in enumerate(originals):
        frames = b.wire_messages(float(i))
        assert len(frames) == len(snap)
        for m in snap:
            if m["type"] == "room_states":
                state = m["system_state"]
        for frame, msg in zip(frames, snap):
            assert not MAC_RE.search(frame), frame
            wire = json.loads(frame)
            if msg["type"] == "room_states":
                if state == "IDLE":
                    assert wire["rooms"] == [] and wire["ranking"] == []
                    continue
            elif msg["type"] == "crew" and state == "IDLE":
                assert wire["tags"] == []
                continue
            assert wire == msg

    assert snapshots == originals, "Broadcaster mutated the source's snapshots"
