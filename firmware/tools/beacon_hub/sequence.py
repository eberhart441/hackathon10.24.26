"""Track packet-counter gaps for one (receiver, transmitter) stream.

Rules (firmware/docs/serial-protocol.md, "Rules for readers"):
- The counter goes up by 1 per packet, so a forward jump of N means N-1 lost packets.
- The same value again is a duplicate and is ignored.
- A counter that goes backwards means the transmitter restarted; that is not loss.
- A huge forward jump (more than `max_gap`) is treated as a discontinuity, not loss.
"""
from __future__ import annotations

from dataclasses import dataclass

_MOD = 1 << 32
_HALF = 1 << 31


@dataclass(frozen=True)
class SeqEvent:
    kind: str  # "first" | "ok" | "gap" | "duplicate" | "restart" | "discontinuity"
    lost: int = 0


class SequenceTracker:
    def __init__(self, max_gap: int = 100_000):
        self.max_gap = max_gap
        self._last: int | None = None
        self.received = 0
        self.lost = 0
        self.restarts = 0
        self.duplicates = 0

    def update(self, seq: int) -> SeqEvent:
        if self._last is None:
            self._last = seq
            self.received += 1
            return SeqEvent("first")
        diff = (seq - self._last) % _MOD
        if diff == 0:
            self.duplicates += 1
            return SeqEvent("duplicate")
        if diff >= _HALF:  # went backwards
            self._last = seq
            self.restarts += 1
            self.received += 1
            return SeqEvent("restart")
        self._last = seq
        self.received += 1
        if diff == 1:
            return SeqEvent("ok")
        if diff - 1 > self.max_gap:
            self.restarts += 1
            return SeqEvent("discontinuity")
        self.lost += diff - 1
        return SeqEvent("gap", diff - 1)

    @property
    def loss_rate(self) -> float:
        total = self.received + self.lost
        return self.lost / total if total else 0.0
