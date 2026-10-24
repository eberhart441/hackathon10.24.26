"""LiveSource end to end on protocol lines: serial text in, dashboard messages out (no hardware)."""

import asyncio
import json
import random
import re

import pytest
from roomsense_hub import CsiRecord, Heartbeat, format_record

from hub.live_source import LiveSource

TX = "f4:65:0b:c4:d6:e4"
MAC = re.compile(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", re.I)
PLAN = {
    "floors": [
        {"id": "F1", "name": "Floor 1", "rooms": [
            {"id": "R1", "name": "Room 101", "polygon": [[0, 0], [4, 0], [4, 3], [0, 3]], "doors": [],
             "furniture": [], "crewSlot": [1, 1]},
            {"id": "R2", "name": "Storage", "simulated": True, "polygon": [[4, 0], [7, 0], [7, 3], [4, 3]],
             "doors": [], "furniture": [], "crewSlot": [5, 1]},
        ]},
    ],
    "nodes": [
        {"id": "TX1", "role": "TX", "room": "R1", "pos": [0, 3], "h": 1},
        {"id": "RX1", "role": "RX", "room": "R1", "pos": [4, 1.5], "h": 1},
        {"id": "RX2", "role": "RX", "room": "R1", "pos": [2, 0], "h": 1},
    ],
    "links": [{"tx": "TX1", "rx": "RX1"}, {"tx": "TX1", "rx": "RX2"}],
}


class Feed:
    """Plays receivers at 100 packets/s with a heartbeat each second, on a fake clock."""

    def __init__(self, src: LiveSource):
        self.src, self.t, self.seq, self.rng = src, 1000.0, 0, random.Random(1)

    def run(self, seconds: float, *, moving=(), silent=(), room="ROOM1", pps=100):
        for step in range(int(seconds * 100)):
            self.seq += 1
            for rx in ("RX1", "RX2"):
                if rx in silent:
                    continue
                if rx in moving:
                    amps = [self.rng.randint(5, 60) for _ in range(64)]
                else:
                    amps = [20 + self.rng.randint(0, 1) for _ in range(64)]
                self.src.feed_line(format_record(CsiRecord(rx, TX, self.seq, self.seq * 10_000, -45, 11,
                                                           tuple(amps))), self.t)
                if step % 100 == 0:
                    self.src.feed_line(format_record(Heartbeat(rx, room, TX, "0.1.0", int(self.t), pps, 150_000,
                                                               0, "HUB")), self.t)
            if step % 50 == 0:
                self.src.tick(self.t)
            self.t += 0.01
        self.src.tick(self.t)

    def frame(self):
        return self.src.frame(self.t)


@pytest.fixture
def plan_path(tmp_path):
    p = tmp_path / "floorplan.json"
    p.write_text(json.dumps(PLAN), encoding="utf-8")
    return p


def make(plan_path, **kw):
    return LiveSource(plan_path, hold_s=20.0, clock=lambda: 0.0, **kw)


def alarm(src, feed):
    src._clock = lambda: feed.t
    asyncio.run(src.trigger_alarm())


def r1(frame):
    return next(r for r in frame["room_states"]["rooms"] if r["room_id"] == "R1")


def test_idle_sends_health_but_no_rooms(plan_path):
    src = make(plan_path)
    feed = Feed(src)
    feed.run(3, moving=("RX2",))
    f = feed.frame()
    assert f["room_states"]["system_state"] == "IDLE"
    assert f["room_states"]["rooms"] == [] and f["room_states"]["ranking"] == []
    assert f["recording"]["indicator"] == "Not recording" and f["recording"]["stored_samples"] == 0
    assert {n["node_id"] for n in f["health"]["nodes"]} == {"RX1", "RX2", "TX1"}


def test_motion_on_one_receiver_makes_the_room_motion_during_an_incident(plan_path):
    src = make(plan_path, with_sim=False)
    feed = Feed(src)
    feed.run(3)  # empty room: learn quiet baselines
    alarm(src, feed)
    feed.run(2, moving=("RX2",))
    room = r1(feed.frame())
    assert room["state"] == "MOTION"
    assert room["alarm_time_state"] == "POSSIBLE"  # snapshot taken before motion (never watched a full hold)
    assert feed.frame()["room_states"]["simulated"] is False


def test_moving_then_still_holds_possible(plan_path):
    src = make(plan_path, with_sim=False)
    feed = Feed(src)
    feed.run(3)
    alarm(src, feed)
    feed.run(2, moving=("RX1",))
    feed.run(4)
    assert r1(feed.frame())["state"] == "POSSIBLE"


def test_receivers_going_silent_make_the_room_unknown_and_raise_faults(plan_path):
    src = make(plan_path, with_sim=False)
    feed = Feed(src)
    feed.run(3)
    alarm(src, feed)
    feed.run(12, silent=("RX1", "RX2"))
    f = feed.frame()
    room = r1(f)
    assert room["state"] == "UNKNOWN" and room["stale"] is True
    status = {n["node_id"]: n["status"] for n in f["health"]["nodes"]}
    assert status == {"RX1": "offline", "RX2": "offline", "TX1": "offline"}
    assert f["health"]["summary"] == "3 faults"


def test_a_collapsed_packet_rate_reports_the_transmitter_dead(plan_path):
    src = make(plan_path, with_sim=False)
    feed = Feed(src)
    feed.run(3)
    feed.run(7, pps=5)
    tx = next(n for n in feed.frame()["health"]["nodes"] if n["node_id"] == "TX1")
    assert tx["status"] == "tx_dead"


def test_simulated_rooms_come_from_the_mock_and_flag_the_message(plan_path):
    src = make(plan_path, with_sim=True)
    feed = Feed(src)
    feed.run(3)
    alarm(src, feed)
    feed.run(1)
    f = feed.frame()["room_states"]
    assert f["simulated"] is True
    assert {r["room_id"] for r in f["rooms"]} == {"R1", "R2"}  # only plan rooms; R2 from the mock
    assert src.room_ids() == {"R1", "R2"}


def test_searched_marks_and_end_incident(plan_path):
    src = make(plan_path, with_sim=False)
    feed = Feed(src)
    feed.run(3)
    alarm(src, feed)
    asyncio.run(src.mark_searched("R1"))
    assert r1(feed.frame())["searched"] is True
    with pytest.raises(KeyError):
        asyncio.run(src.mark_searched("R9"))
    asyncio.run(src.end_incident())
    assert feed.frame()["room_states"]["rooms"] == []


def test_no_mac_address_or_raw_csi_ever_reaches_a_message(plan_path):
    src = make(plan_path, with_sim=True)
    feed = Feed(src)
    feed.run(3)
    alarm(src, feed)
    feed.run(3, moving=("RX1",))
    feed.run(11, silent=("RX2",))
    text = json.dumps(feed.frame())
    assert not MAC.search(text)
    assert "amplitude" not in text and "activity" not in text


def test_the_floor_plan_decides_the_room_even_if_the_board_says_otherwise(plan_path, caplog):
    src = make(plan_path, with_sim=False)
    feed = Feed(src)
    feed.run(3, room="ROOM1")
    alarm(src, feed)
    feed.run(2, moving=("RX1",), room="ROOM1")
    assert r1(feed.frame())["state"] == "MOTION"
    assert any("floor plan puts it in R1" in m for m in caplog.messages)


def test_a_plan_without_receivers_is_refused(tmp_path):
    p = tmp_path / "fp.json"
    p.write_text(json.dumps({**PLAN, "nodes": [], "links": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="no receiver"):
        LiveSource(p)
