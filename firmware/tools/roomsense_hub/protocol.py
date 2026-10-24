"""Parse and format the node serial protocol (see firmware/docs/serial-protocol.md).

`parse_line` is total: it returns a record, or None for anything that is not a
valid protocol record (boot-ROM text, ESP-IDF logs, partial lines, garbage).
It never raises.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Union

AMPLITUDE_COUNT = 64
VALID_ROLES = ("tx", "rx", "tag")
U32_MAX = 4294967295

_NAME = re.compile(r"^[A-Za-z0-9_-]{1,15}$")
_TAG_ID = re.compile(r"^[A-Za-z0-9_-]{1,7}$")
_VERSION = re.compile(r"^[A-Za-z0-9._+-]{1,31}$")
_MAC = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
_UINT = re.compile(r"^[0-9]{1,10}$")
_INT = re.compile(r"^-?[0-9]{1,4}$")
_DECIMAL = re.compile(r"^-?[0-9]{1,4}(\.[0-9]{1,3})?$")


@dataclass(frozen=True)
class Boot:
    node_id: str
    role: str
    room_id: str
    fw_version: str
    channel: int
    bandwidth: str


@dataclass(frozen=True)
class Heartbeat:
    node_id: str
    role: str
    room_id: str
    uptime_ms: int
    pps: int
    channel: int
    dropped: int


@dataclass(frozen=True)
class CsiRecord:
    node_id: str
    room_id: str
    tx_mac: str
    seq: int
    t_us: int
    rssi: int
    channel: int
    amplitudes: tuple[int, ...]


@dataclass(frozen=True)
class TagSummary:
    node_id: str
    room_id: str
    tag_id: str
    packets_heard: int
    mean_rssi: float
    max_rssi: int


@dataclass(frozen=True)
class Response:
    """Reply to a host command: OK, ERR, CFG or PONG lines."""

    kind: str
    fields: tuple[str, ...]


Record = Union[Boot, Heartbeat, CsiRecord, TagSummary, Response]


def _uint(text: str, maximum: int = U32_MAX) -> int | None:
    if not _UINT.match(text):
        return None
    value = int(text)
    return value if value <= maximum else None


def _int(text: str, low: int, high: int) -> int | None:
    if not _INT.match(text):
        return None
    value = int(text)
    return value if low <= value <= high else None


def _channel(text: str) -> int | None:
    return _int(text, 1, 14)


def _parse_boot(f: list[str]) -> Boot | None:
    if len(f) != 6:
        return None
    node_id, role, room_id, fw_version, channel, bandwidth = f
    ch = _channel(channel)
    if not (_NAME.match(node_id) and role in VALID_ROLES and _NAME.match(room_id)
            and _VERSION.match(fw_version) and ch is not None and bandwidth in ("HT20", "HT40")):
        return None
    return Boot(node_id, role, room_id, fw_version, ch, bandwidth)


def _parse_heartbeat(f: list[str]) -> Heartbeat | None:
    if len(f) != 7:
        return None
    node_id, role, room_id, uptime, pps, channel, dropped = f
    up, rate, ch, drop = _uint(uptime), _uint(pps, 100000), _channel(channel), _uint(dropped)
    if not (_NAME.match(node_id) and role in VALID_ROLES and _NAME.match(room_id)
            and up is not None and rate is not None and ch is not None and drop is not None):
        return None
    return Heartbeat(node_id, role, room_id, up, rate, ch, drop)


def _parse_csi(f: list[str]) -> CsiRecord | None:
    if len(f) < 9:
        return None
    node_id, room_id, tx_mac, seq, t_us, rssi, channel, n = f[:8]
    count = _uint(n, 1024)
    if count != AMPLITUDE_COUNT or len(f) != 8 + count:
        return None
    s, t, r, ch = _uint(seq), _uint(t_us), _int(rssi, -128, 0), _channel(channel)
    if not (_NAME.match(node_id) and _NAME.match(room_id) and _MAC.match(tx_mac)
            and s is not None and t is not None and r is not None and ch is not None):
        return None
    amps: list[int] = []
    for text in f[8:]:
        value = _uint(text, 255)
        if value is None:
            return None
        amps.append(value)
    return CsiRecord(node_id, room_id, tx_mac, s, t, r, ch, tuple(amps))


def _parse_tag(f: list[str]) -> TagSummary | None:
    if len(f) != 6:
        return None
    node_id, room_id, tag_id, heard, mean_rssi, max_rssi = f
    h, mx = _uint(heard, 100000), _int(max_rssi, -128, 0)
    if not (_NAME.match(node_id) and _NAME.match(room_id) and _TAG_ID.match(tag_id)
            and h is not None and h >= 1 and mx is not None and _DECIMAL.match(mean_rssi)):
        return None
    mean = float(mean_rssi)
    if not -128.0 <= mean <= 0.0:
        return None
    return TagSummary(node_id, room_id, tag_id, h, mean, mx)


_PARSERS = {
    "BOOT": _parse_boot,
    "HB": _parse_heartbeat,
    "CSI": _parse_csi,
    "TAG": _parse_tag,
}
_RESPONSE_KINDS = ("OK", "ERR", "CFG", "PONG")


def parse_line(line: str) -> Record | None:
    """Return the record in `line`, or None if it is not a valid protocol record."""
    try:
        text = line.rstrip("\r\n")
        if not text or "\n" in text or "\r" in text:
            return None
        fields = text.split(",")
        kind = fields[0]
        parser = _PARSERS.get(kind)
        if parser is not None:
            return parser(fields[1:])
        if kind in _RESPONSE_KINDS and all(fields):
            return Response(kind, tuple(fields[1:]))
        return None
    except (ValueError, IndexError):  # defensive: never let a bad line escape
        return None


def format_record(record: Record) -> str:
    """Format a record exactly as the firmware does (without the trailing newline)."""
    if isinstance(record, Boot):
        return ",".join(["BOOT", record.node_id, record.role, record.room_id,
                         record.fw_version, str(record.channel), record.bandwidth])
    if isinstance(record, Heartbeat):
        return ",".join(["HB", record.node_id, record.role, record.room_id, str(record.uptime_ms),
                         str(record.pps), str(record.channel), str(record.dropped)])
    if isinstance(record, CsiRecord):
        head = ["CSI", record.node_id, record.room_id, record.tx_mac, str(record.seq),
                str(record.t_us), str(record.rssi), str(record.channel), str(len(record.amplitudes))]
        return ",".join(head + [str(a) for a in record.amplitudes])
    if isinstance(record, TagSummary):
        return ",".join(["TAG", record.node_id, record.room_id, record.tag_id,
                         str(record.packets_heard), f"{record.mean_rssi:.1f}", str(record.max_rssi)])
    if isinstance(record, Response):
        return ",".join([record.kind, *record.fields])
    raise TypeError(f"cannot format {type(record).__name__}")
