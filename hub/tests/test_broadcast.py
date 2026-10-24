"""Example tests for redact_for_wire and Broadcaster (Req 7.7, 14.1, 20.2, 20.3)."""

from __future__ import annotations

import asyncio
import copy
import json

import pytest

from hub.web.broadcast import Broadcaster, redact_for_wire
from hub.web.source import StateSource

ROOM = {"room_id": "R1", "state": "MOTION"}


def room_states(system_state: str) -> dict:
    return {
        "type": "room_states",
        "ts": 0,
        "system_state": system_state,
        "simulated": True,
        "rooms": [dict(ROOM)],
        "ranking": ["R1"],
    }


def health() -> dict:
    return {"type": "health", "ts": 0, "summary": "all ok", "nodes": [], "tag_faults": []}


def crew() -> dict:
    return {
        "type": "crew",
        "ts": 0,
        "tags": [{"tag_id": "E1", "room_id": "R1"}],
        "floor_crew_counts": {"F1": 1},
    }


class FakeSource:
    def __init__(self, system_state: str = "IDLE") -> None:
        self.system_state = system_state
        self.snapshots: list[float] = []

    def room_ids(self) -> set[str]:
        return {"R1"}

    def snapshot(self, now: float) -> list[dict]:
        self.snapshots.append(now)
        return [room_states(self.system_state), health(), crew()]

    def trigger_alarm(self, now: float) -> dict:
        self.system_state = "ALARM_ACTIVE"
        return {"system_state": "ALARM_ACTIVE", "simulated": True}

    def end_incident(self, now: float) -> dict:
        self.system_state = "IDLE"
        return {"system_state": "IDLE"}

    def mark_searched(self, room_id: str, now: float) -> None:
        pass


class FakeSocket:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[dict] = []
        self.closed: int | None = None

    async def send_text(self, data: str) -> None:
        if self.fail:
            raise ConnectionError("gone")
        self.sent.append(json.loads(data))

    async def close(self, code: int = 1000) -> None:
        self.closed = code


class FakeClock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


# --- redact_for_wire ----------------------------------------------------


def test_idle_room_states_are_emptied():
    m = redact_for_wire(room_states("IDLE"))
    assert m["rooms"] == [] and m["ranking"] == []
    assert m["system_state"] == "IDLE" and m["simulated"] is True


def test_alarm_room_states_pass_through():
    msg = room_states("ALARM_ACTIVE")
    assert redact_for_wire(msg) == msg


def test_idle_crew_is_emptied_and_alarm_crew_passes():
    m = redact_for_wire(crew(), "IDLE")
    assert m["tags"] == [] and m["floor_crew_counts"] == {}
    assert redact_for_wire(crew(), "ALARM_ACTIVE") == crew()


def test_redact_never_mutates_input():
    for msg, state in [(room_states("IDLE"), None), (crew(), "IDLE"), (health(), "IDLE")]:
        before = copy.deepcopy(msg)
        out = redact_for_wire(msg, state)
        assert msg == before
        assert out is not msg


def test_fake_source_satisfies_protocol():
    assert isinstance(FakeSource(), StateSource)


# --- Broadcaster --------------------------------------------------------


def test_publish_now_sends_redacted_snapshot_to_all_sockets():
    async def go():
        src, clock = FakeSource("IDLE"), FakeClock()
        b = Broadcaster(src, clock)
        a, p = FakeSocket(), FakeSocket()
        b.register(a, "local")
        b.register(p, "phone")
        await b.publish_now()
        return a, p

    a, p = asyncio.run(go())
    for s in (a, p):
        types = [m["type"] for m in s.sent]
        assert types == ["room_states", "health", "crew"]
        assert s.sent[0]["rooms"] == [] and s.sent[0]["ranking"] == []
        assert s.sent[2]["tags"] == []


def test_alarm_snapshot_is_not_redacted():
    async def go():
        b = Broadcaster(FakeSource("ALARM_ACTIVE"), FakeClock())
        s = FakeSocket()
        b.register(s, "phone")
        await b.publish_now()
        return s

    s = asyncio.run(go())
    assert s.sent[0]["rooms"] == [ROOM] and s.sent[0]["ranking"] == ["R1"]
    assert s.sent[2]["tags"] == [{"tag_id": "E1", "room_id": "R1"}]


def test_run_publishes_health_at_1hz_with_fake_clock():
    src, clock = FakeSource("IDLE"), FakeClock()
    sock = FakeSocket()
    sleeps: list[float] = []

    async def fake_sleep(dt: float) -> None:
        sleeps.append(dt)
        clock.t += dt
        if len(sleeps) >= 5:
            raise asyncio.CancelledError

    async def go():
        b = Broadcaster(sleep=fake_sleep)
        b.register(sock, "phone")
        with pytest.raises(asyncio.CancelledError):
            await b.run(src, clock, period_s=1.0)

    asyncio.run(go())
    assert src.snapshots == [100.0, 101.0, 102.0, 103.0, 104.0]
    assert all(dt == pytest.approx(1.0) for dt in sleeps)
    health_count = sum(1 for m in sock.sent if m["type"] == "health")
    assert health_count == 5


def test_failing_socket_is_dropped_others_still_receive():
    async def go():
        b = Broadcaster(FakeSource("IDLE"), FakeClock())
        bad, good = FakeSocket(fail=True), FakeSocket()
        b.register(bad, "phone")
        b.register(good, "local")
        await b.publish_now()
        await b.publish_now()
        return b, bad, good

    b, bad, good = asyncio.run(go())
    assert b.kind_of(bad) is None
    assert b.kind_of(good) == "local"
    assert sum(1 for m in good.sent if m["type"] == "health") == 2


def test_close_kind_closes_only_phone_sockets():
    async def go():
        b = Broadcaster(FakeSource("IDLE"), FakeClock())
        p1, p2, local = FakeSocket(), FakeSocket(), FakeSocket()
        b.register(p1, "phone")
        b.register(p2, "phone")
        b.register(local, "local")
        n = await b.close_kind("phone")
        await b.publish_now()
        return b, n, p1, p2, local

    b, n, p1, p2, local = asyncio.run(go())
    assert n == 2
    assert p1.closed is not None and p2.closed is not None and local.closed is None
    assert p1.sent == [] and p2.sent == []
    assert list(b.sockets.values()) == ["local"]
    assert len(local.sent) == 3
