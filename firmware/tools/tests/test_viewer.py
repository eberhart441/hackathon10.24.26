"""The live viewer's measuring logic, with plain strings (no browser, no hardware)."""
import json
import random
from pathlib import Path

from roomsense_hub import CsiRecord, Heartbeat, format_record
from roomsense_hub.viewer import PAGE, Hub

FIXTURE = Path(__file__).parent / "fixtures" / "sample_capture.log"
TX = "f4:65:0b:c4:d6:e4"


def csi_line(seq, amps, node="RX1"):
    return format_record(CsiRecord(node, TX, seq, seq * 10_000, -45, 11, tuple(amps)))


def feed_steady(hub, start, count, t0=0.0):
    rng = random.Random(1)
    for i in range(count):
        amps = [20 + rng.randint(0, 1) for _ in range(64)]
        hub.feed_line(csi_line(start + i, amps), t0 + i * 0.01)
    return t0 + count * 0.01


def snapshot(hub, now):
    return json.loads(hub.snapshot_json(now))["nodes"][0]


def test_a_steady_signal_reads_quiet_and_a_disturbed_one_reads_motion():
    hub = Hub()
    now = feed_steady(hub, 0, 150)
    quiet = snapshot(hub, now)
    assert quiet["state"] == "quiet"

    rng = random.Random(2)
    for i in range(100):  # the signal starts swinging hard
        amps = [rng.randint(5, 60) for _ in range(64)]
        hub.feed_line(csi_line(150 + i, amps), now + i * 0.01)
    moving = snapshot(hub, now + 1.0)
    assert moving["state"] == "motion"
    assert moving["activity"] > quiet["activity"]


def test_it_warms_up_before_judging():
    hub = Hub()
    now = feed_steady(hub, 0, 10)
    assert snapshot(hub, now)["state"] == "warming"


def test_no_data_for_a_while_is_no_signal_not_quiet():
    hub = Hub()
    now = feed_steady(hub, 0, 150)
    assert snapshot(hub, now + 5.0)["state"] == "nosignal"


def test_heartbeat_gives_health_and_goes_offline_after_ten_seconds():
    hub = Hub()
    hub.feed_line(format_record(Heartbeat("RX1", "R1", TX, "0.1.0", 5000, 100, 200000, 0, "HUB")), 100.0)
    assert snapshot(hub, 105.0)["online"] is True
    late = snapshot(hub, 111.0)
    assert late["online"] is False and late["room"] == "R1" and late["measuredPps"] == 100


def test_lost_packets_and_new_columns_are_reported_once():
    hub = Hub()
    for seq, t in [(1, 0.0), (2, 0.01), (5, 0.02)]:  # 3 and 4 lost
        hub.feed_line(csi_line(seq, [10] * 64), t)
    first = snapshot(hub, 0.1)
    assert first["lost"] == 2 and len(first["columns"]) == 3 and len(first["columns"][0]) == 64
    assert snapshot(hub, 0.2)["columns"] == []  # already delivered


def test_garbage_lines_are_ignored():
    hub = Hub()
    hub.feed_line("I (12) wifi: connected", 0.0)
    hub.feed_line("CSI,broken", 0.0)
    assert json.loads(hub.snapshot_json(0.0))["nodes"] == []


def test_the_sample_capture_shows_up():
    hub = Hub()
    for i, line in enumerate(FIXTURE.read_text(encoding="utf-8").splitlines()):
        hub.feed_line(line, i * 0.01)
    node = snapshot(hub, 0.5)
    assert node["id"] == "RX1" and node["room"] == "R1" and node["lost"] == 0


def test_the_page_never_says_empty():
    assert "empty" not in PAGE.lower().replace("never means a room is empty", "")
