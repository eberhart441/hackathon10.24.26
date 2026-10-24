"""Receiver gain correction for CSI amplitudes.

The classic ESP32 does not report its receive gain, and its automatic gain control changes it
on its own. A gain change multiplies every subcarrier of a packet by the same factor: as a
one-packet spike (about 3x) or as a step that lasts. Either one moves the raw amplitudes and
would read as motion.

Dividing each packet by its own mean over the subcarriers that carry signal removes any common
factor exactly. What motion does is uneven across subcarriers (the multipath pattern changes),
and that survives. The packet is then scaled to a fixed reference level for the link, so
activity numbers keep the units and thresholds they had before.

Cost: a change that really is the same on every subcarrier (for example the whole signal
dimming evenly) is removed too. Motion between the boards also reshapes the pattern, so it
still shows.
"""
from __future__ import annotations

import statistics
from collections.abc import Sequence

REFERENCE_PACKETS = 21  # packets used to fix a link's reference level


def live_mean(amplitudes: Sequence[float]) -> float:
    """Mean over the subcarriers that carry signal (null and guard subcarriers read 0)."""
    live = [a for a in amplitudes if a]
    return statistics.fmean(live) if live else 0.0


def normalize_gain(amplitudes: Sequence[float], reference: float) -> tuple[float, ...]:
    """Scale a packet so its live mean equals `reference`. Zeros stay zero; an all-zero packet
    stays all zero."""
    mean = live_mean(amplitudes)
    if mean <= 0 or reference <= 0:
        return tuple(0.0 for _ in amplitudes)
    k = reference / mean
    return tuple(a * k for a in amplitudes)


class GainReference:
    """Learns a link's reference level once (the median packet mean of its first packets) and
    then keeps it fixed, so a later gain step cannot drag it along."""

    def __init__(self, packets: int = REFERENCE_PACKETS) -> None:
        self._packets = packets
        self._means: list[float] = []
        self.value: float | None = None

    def update(self, amplitudes: Sequence[float]) -> float:
        """Feed one packet; returns the reference to normalize it with."""
        if self.value is not None:
            return self.value
        mean = live_mean(amplitudes)
        if mean > 0:
            self._means.append(mean)
        current = statistics.median(self._means) if self._means else 0.0
        if len(self._means) >= self._packets:
            self.value = current
        return current

    def reset(self) -> None:
        self._means.clear()
        self.value = None
