"""Turn serial lines into records, per-link statistics, node health, and CSV rows.

`Ingest.feed_line` is the single seam: give it text lines (from a serial port, a
file, or the simulator) and it reports what it understood. Nothing here touches
hardware, so the whole pipeline front end can be tested with plain strings.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from .protocol import (
    AMPLITUDE_COUNT,
    Boot,
    CsiRecord,
    Heartbeat,
    Record,
    TagSummary,
    parse_line,
)
from .sequence import SequenceTracker

CSV_COLUMNS = (
    ["arrival_unix_s", "node_id", "room_id", "tx_mac", "seq", "t_us", "rssi", "channel"]
    + [f"a{i}" for i in range(AMPLITUDE_COUNT)]
)


class CsvSink:
    """Appends CSI records to a CSV file as they arrive (flushed every row)."""

    def __init__(self, handle: TextIO):
        self._handle = handle
        self._writer = csv.writer(handle)
        self._writer.writerow(CSV_COLUMNS)
        handle.flush()
        self.rows = 0

    @classmethod
    def open(cls, path: Path) -> "CsvSink":
        path.parent.mkdir(parents=True, exist_ok=True)
        return cls(path.open("w", newline="", encoding="utf-8"))

    def write(self, arrival_s: float, record: CsiRecord) -> None:
        self._writer.writerow(
            [f"{arrival_s:.6f}", record.node_id, record.room_id, record.tx_mac, record.seq,
             record.t_us, record.rssi, record.channel, *record.amplitudes]
        )
        self._handle.flush()
        self.rows += 1

    def close(self) -> None:
        self._handle.close()


@dataclass
class NodeStats:
    node_id: str
    role: str | None = None
    room_id: str | None = None
    boot: Boot | None = None
    last_heartbeat: Heartbeat | None = None
    last_seen_s: float | None = None
    last_heartbeat_s: float | None = None
    csi_records: int = 0
    tag_summaries: int = 0


@dataclass
class StreamStats:
    node_id: str
    tx_mac: str
    received: int
    lost: int
    restarts: int
    duplicates: int
    loss_rate: float


@dataclass
class Ingest:
    sink: CsvSink | None = None
    offline_after_s: float = 10.0
    nodes: dict[str, NodeStats] = field(default_factory=dict)
    streams: dict[tuple[str, str], SequenceTracker] = field(default_factory=dict)
    ignored_lines: int = 0
    total_lines: int = 0

    def feed_line(self, line: str, arrival_s: float) -> Record | None:
        """Process one line. Returns the record if the line was valid, else None."""
        self.total_lines += 1
        record = parse_line(line)
        if record is None:
            self.ignored_lines += 1
            return None
        if isinstance(record, CsiRecord):
            node = self._node(record.node_id)
            node.room_id = record.room_id
            node.csi_records += 1
            node.last_seen_s = arrival_s
            tracker = self.streams.setdefault((record.node_id, record.tx_mac), SequenceTracker())
            tracker.update(record.seq)
            if self.sink is not None:
                self.sink.write(arrival_s, record)
        elif isinstance(record, Heartbeat):
            node = self._node(record.node_id)
            node.role, node.room_id = record.role, record.room_id
            node.last_heartbeat = record
            node.last_heartbeat_s = node.last_seen_s = arrival_s
        elif isinstance(record, Boot):
            node = self._node(record.node_id)
            node.role, node.room_id, node.boot = record.role, record.room_id, record
            node.last_seen_s = arrival_s
        elif isinstance(record, TagSummary):
            node = self._node(record.node_id)
            node.room_id = record.room_id
            node.tag_summaries += 1
            node.last_seen_s = arrival_s
        return record

    def _node(self, node_id: str) -> NodeStats:
        return self.nodes.setdefault(node_id, NodeStats(node_id))

    def offline_nodes(self, now_s: float) -> list[str]:
        """Nodes whose last heartbeat is older than the threshold (or that never sent one)."""
        late = []
        for node in self.nodes.values():
            if node.last_heartbeat_s is None or now_s - node.last_heartbeat_s > self.offline_after_s:
                late.append(node.node_id)
        return sorted(late)

    def stream_stats(self) -> list[StreamStats]:
        return [
            StreamStats(node, mac, t.received, t.lost, t.restarts, t.duplicates, t.loss_rate)
            for (node, mac), t in sorted(self.streams.items())
        ]
