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


def test_a_blocked_flat_link_reads_weak_signal_not_quiet():
    """Covering the antenna makes the numbers go flat. That must not look like a calm room."""
    hub = Hub()
    now = feed_steady(hub, 0, 150)
    assert snapshot(hub, now)["state"] == "quiet"
    for i in range(120):  # signal collapses to a constant trickle
        hub.feed_line(csi_line(150 + i, [1] * 64), now + i * 0.01)
    assert snapshot(hub, now + 1.3)["state"] == "weak"


def test_a_very_low_rssi_reads_weak_signal():
    hub = Hub()
    rng = random.Random(3)
    for i in range(150):
        amps = [20 + rng.randint(0, 3) for _ in range(64)]
        hub.feed_line(format_record(CsiRecord("RX1", TX, i, i * 10_000, -92, 11, tuple(amps))), i * 0.01)
    assert snapshot(hub, 1.5)["state"] == "weak"


def test_weak_signal_does_not_poison_the_learned_baseline():
    hub = Hub()
    now = feed_steady(hub, 0, 150)
    before = hub.nodes["RX1"].baseline
    for i in range(120):
        hub.feed_line(csi_line(150 + i, [1] * 64), now + i * 0.01)
    snapshot(hub, now + 1.3)
    assert hub.nodes["RX1"].baseline == before


def test_two_receivers_are_tracked_independently():
    hub = Hub()
    rng = random.Random(4)
    for i in range(150):
        quiet = [20 + rng.randint(0, 1) for _ in range(64)]
        hub.feed_line(csi_line(i, quiet, node="RX1"), i * 0.01)
        hub.feed_line(csi_line(i, quiet, node="RX2"), i * 0.01)
    assert [n["id"] for n in json.loads(hub.snapshot_json(1.5))["nodes"]] == ["RX1", "RX2"]
    for i in range(100):  # only RX2 sees a disturbance
        hub.feed_line(csi_line(150 + i, [20 + rng.randint(0, 1) for _ in range(64)], node="RX1"), 1.5 + i * 0.01)
        hub.feed_line(csi_line(150 + i, [rng.randint(5, 60) for _ in range(64)], node="RX2"), 1.5 + i * 0.01)
    nodes = {n["id"]: n for n in json.loads(hub.snapshot_json(2.5))["nodes"]}
    assert nodes["RX1"]["state"] == "quiet"
    assert nodes["RX2"]["state"] == "motion"


def test_the_page_has_the_room_overview_and_the_weak_signal_label():
    assert "drawRoom" in PAGE and "drawTimeline" in PAGE and "WEAK SIGNAL" in PAGE


def test_reopening_a_port_does_not_count_unread_packets_as_lost():
    """Unplug/replug (or restarting the viewer) skips packets nobody read; the board did not lose them."""
    hub = Hub()
    for seq in range(1, 51):
        hub.feed_line(csi_line(seq, [20] * 64), seq * 0.01, port="COM3")
    hub.port_reset("COM3")  # port reopened; the board kept transmitting meanwhile
    for seq in range(5000, 5050):
        hub.feed_line(csi_line(seq, [20] * 64), 60 + seq * 0.0001, port="COM3")
    assert snapshot(hub, 61.0)["lost"] == 0


def test_a_real_gap_after_the_reset_is_still_counted():
    hub = Hub()
    hub.feed_line(csi_line(1, [20] * 64), 0.0, port="COM3")
    hub.port_reset("COM3")
    for seq in [10, 11, 15]:  # 12-14 genuinely missing
        hub.feed_line(csi_line(seq, [20] * 64), 1.0, port="COM3")
    assert snapshot(hub, 1.1)["lost"] == 3


def test_one_packet_gain_glitches_do_not_look_like_motion_but_are_counted():
    """Real captures show about one packet in 350 arriving ~3x too strong on every subcarrier."""
    hub = Hub()
    rng = random.Random(5)
    seen_motion = False
    for i in range(1200):
        amps = [20 + rng.randint(0, 1) for _ in range(64)]
        if i % 120 == 60:
            amps = [a * 3 for a in amps]  # a glitch packet
        hub.feed_line(csi_line(i, amps), i * 0.01)
        if i % 10 == 0 and i > 150:
            seen_motion |= snapshot(hub, i * 0.01)["state"] == "motion"
    assert not seen_motion
    assert snapshot(hub, 12.0)["glitches"] >= 8


def test_a_sustained_disturbance_is_still_motion_with_the_glitch_filter():
    hub = Hub()
    now = feed_steady(hub, 0, 150)
    assert snapshot(hub, now)["state"] == "quiet"  # learn the quiet baseline first
    rng = random.Random(6)
    for i in range(100):
        hub.feed_line(csi_line(150 + i, [20 + rng.randint(-12, 25) for _ in range(64)]), now + i * 0.01)
    assert snapshot(hub, now + 1.0)["state"] == "motion"
