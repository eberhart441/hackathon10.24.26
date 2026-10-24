"""Ingest at the serial-line seam: lines in, records / statistics / CSV out."""
import csv
import io
from datetime import datetime, timezone
from pathlib import Path

import pytest

from roomsense_hub import CsiRecord, Heartbeat, format_record
from roomsense_hub.capture import CaptureError, check_training_allowed, output_paths
from roomsense_hub.ingest import CSV_COLUMNS, CsvSink, Ingest

FIXTURE = Path(__file__).parent / "fixtures" / "sample_capture.log"
TX = "1a:00:00:00:00:00"


def csi(node="RX1", seq=0, t_us=0, mac=TX, room="ROOM1"):
    amps = tuple((seq + i) % 256 for i in range(64))
    return format_record(CsiRecord(node, room, mac, seq, t_us, -50, 11, amps)) + "\n"


def hb(node="RX1", role="rx", uptime=1000):
    return format_record(Heartbeat(node, role, "ROOM1", uptime, 100, 11, 0)) + "\n"


def test_noise_lines_are_counted_and_ignored():
    ingest = Ingest()
    assert ingest.feed_line("I (12) wifi: connected", 0.0) is None
    assert ingest.feed_line(csi(seq=1), 0.1) is not None
    assert (ingest.total_lines, ingest.ignored_lines) == (2, 1)


def test_loss_is_tracked_per_receiver_and_transmitter():
    ingest = Ingest()
    for seq in [1, 2, 3, 6, 7]:  # 4 and 5 lost on RX1
        ingest.feed_line(csi("RX1", seq), seq * 0.01)
    for seq in [1, 2, 3, 4]:
        ingest.feed_line(csi("RX2", seq), seq * 0.01)
    stats = {s.node_id: s for s in ingest.stream_stats()}
    assert (stats["RX1"].received, stats["RX1"].lost) == (5, 2)
    assert (stats["RX2"].received, stats["RX2"].lost) == (4, 0)


def test_two_transmitters_heard_by_one_receiver_are_separate_streams():
    ingest = Ingest()
    ingest.feed_line(csi("RX1", 1, mac=TX), 0)
    ingest.feed_line(csi("RX1", 1, mac="1a:00:00:00:00:01"), 0)
    assert len(ingest.stream_stats()) == 2


def test_a_node_without_heartbeat_for_ten_seconds_is_offline():
    ingest = Ingest()
    ingest.feed_line(hb("RX1"), 100.0)
    ingest.feed_line(hb("RX2"), 100.0)
    ingest.feed_line(hb("RX1"), 108.0)
    assert ingest.offline_nodes(109.0) == []
    assert ingest.offline_nodes(111.0) == ["RX2"]  # RX2 last heard 11 s ago
    assert ingest.offline_nodes(119.0) == ["RX1", "RX2"]


def test_csi_alone_does_not_count_as_a_heartbeat():
    ingest = Ingest()
    ingest.feed_line(csi("RX1", 1), 1.0)
    assert ingest.offline_nodes(2.0) == ["RX1"]  # streaming data but never said hello


def test_csv_gets_only_csi_rows_with_all_columns():
    handle = io.StringIO()
    ingest = Ingest(sink=CsvSink(handle))
    ingest.feed_line(hb(), 1.0)
    ingest.feed_line("garbage", 1.0)
    ingest.feed_line(csi("RX1", 7, t_us=12345), 2.5)
    rows = list(csv.reader(io.StringIO(handle.getvalue())))
    assert rows[0] == CSV_COLUMNS
    assert len(rows) == 2
    row = dict(zip(CSV_COLUMNS, rows[1]))
    assert (row["node_id"], row["seq"], row["t_us"], row["tx_mac"]) == ("RX1", "7", "12345", TX)
    assert row["arrival_unix_s"] == "2.500000"
    assert [int(row[f"a{i}"]) for i in range(64)] == [(7 + i) % 256 for i in range(64)]


def test_the_sample_capture_parses_cleanly():
    """Golden fixture: a capture with boot noise, logs and a half-line at the start."""
    ingest = Ingest()
    for i, line in enumerate(FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True)):
        ingest.feed_line(line, i * 0.01)
    assert ingest.total_lines > ingest.ignored_lines > 0
    assert {n.role for n in ingest.nodes.values()} == {"rx"}
    assert sum(n.csi_records for n in ingest.nodes.values()) >= 20
    assert all(s.lost == 0 for s in ingest.stream_stats())


def test_training_requires_consent_and_an_authorized_installer(tmp_path):
    allow = tmp_path / "allow.txt"
    allow.write_text("# two installers\nAlice\nbob\n", encoding="utf-8")
    check_training_allowed("alice", True, allow)  # case-insensitive, no error
    with pytest.raises(CaptureError, match="consent"):
        check_training_allowed("alice", False, allow)
    with pytest.raises(CaptureError, match="not an authorized"):
        check_training_allowed("mallory", True, allow)
    with pytest.raises(CaptureError, match="allowlist"):
        check_training_allowed("alice", True, tmp_path / "missing.txt")


def test_each_recording_goes_to_its_own_labeled_file(tmp_path):
    csv_path, meta_path = output_paths(tmp_path, "still_present", datetime(2026, 10, 24, 15, 30, 5, tzinfo=timezone.utc))
    assert csv_path.name == "still_present_20261024T153005Z.csv"
    assert meta_path.name == "still_present_20261024T153005Z.meta.json"
