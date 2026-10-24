"""Relay mode (experimental) runs links at 50 packets/s: that must not read as packet loss, while real loss still does."""
import json
import random

from beacon_hub import CsiRecord, Heartbeat, format_record
from beacon_hub.locate import Layout, Link
from beacon_hub.viewer import Hub

TX = "4c:c3:82:28:1d:0c"


def hub_at(pps, board_pps, keep=lambda i: True, seconds=3):
    """One receiver whose transmitter sends pps; the board reports board_pps; keep(i) drops lines in transit."""
    hub = Hub(Layout((10.0, 10.0), (Link("RX1", (0, 0), (10, 10)), Link("RX2", (10, 0), (0, 10)))))
    rng = random.Random(3)
    for i in range(pps * seconds):
        t = i / pps
        for node in ("RX1", "RX2"):
            if node == "RX1" and not keep(i):
                continue
            amps = [20 + rng.randint(0, 1) for _ in range(64)]
            hub.feed_line(format_record(CsiRecord(node, TX, i, int(t * 1e6), -45, 11, tuple(amps))), t)
        if i % pps == 0:
            for node in ("RX1", "RX2"):
                hub.feed_line(format_record(Heartbeat(node, "R1", TX, "0.1.0", int(t * 1000), board_pps, 200000, 0, "HUB")), t)
    return {n["id"]: n["offReason"] for n in json.loads(hub.snapshot_json(seconds))["nodes"]}


def test_a_relayed_link_at_50_per_second_is_healthy():
    assert hub_at(50, 50)["RX1"] is None


def test_lines_lost_on_the_way_to_the_laptop_still_count_as_loss():
    # the board received 50/s but only 1 in 5 lines reached the laptop (relay or USB dropping them)
    assert hub_at(50, 50, keep=lambda i: i % 5 == 0)["RX1"].startswith("losing packets")


def test_a_backlog_burst_does_not_make_a_healthy_link_look_lossy():
    # The laptop stalls, then 300 lines arrive within one second (or a port opens on a full buffer);
    # afterwards the link runs at its normal 100/s and the board reports 100/s.
    hub = Hub(Layout((10.0, 10.0), (Link("RX1", (0, 0), (10, 10)),)))
    rng = random.Random(3)
    seq = 0

    def line(t):
        nonlocal seq
        seq += 1
        amps = [20 + rng.randint(0, 1) for _ in range(64)]
        hub.feed_line(format_record(CsiRecord("RX1", TX, seq, int(t * 1e6), -45, 11, tuple(amps))), t)

    for i in range(300):
        line(0.5 + i / 300)
    hub.feed_line(format_record(Heartbeat("RX1", "R1", TX, "0.1.0", 1000, 100, 200000, 0, "HUB")), 1.0)
    hub.snapshot_json(1.5)  # the burst is seen
    for i in range(500):
        t = 1.5 + i / 100
        line(t)
        if i % 100 == 0:
            hub.feed_line(format_record(Heartbeat("RX1", "R1", TX, "0.1.0", int(t * 1000), 100, 200000, 0, "HUB")), t)
    assert json.loads(hub.snapshot_json(6.5))["nodes"][0]["offReason"] is None
