"""Room state from live link readings (pure, injected clock).

This is the parent design's state engine (design.md, "Room-state model with Last_Evidence hold")
driven by the per-link activity heuristic in firmware/tools/roomsense_hub/viewer.py, because no
trained classifier exists yet. The rules that keep it honest are the design's:

  - Four states only. MOTION never goes straight to NO_DETECTION; it passes through POSSIBLE.
  - After motion stops the room holds POSSIBLE for HOLD_S since the last evidence.
  - With no classifier there is no "empty, high confidence" reading. NO_DETECTION therefore needs
    every link of the room healthy and quiet, continuously, for HOLD_S. Quiet is never "empty".
  - A room with no usable link is UNKNOWN and stale (last known state + age), and stays UNKNOWN
    for RECOVERY_S after its links come back.
  - Confidence is a heuristic (activity margin x link quality), capped at 49 when a heartbeat is
    late. It is not a model probability.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

HOLD_S = 300.0
HB_DEGRADED_S = 3.0
HB_OFFLINE_S = 10.0
RECOVERY_S = 10.0
PPS_NOMINAL = 100
PPS_MIN = 20  # below this the link is not judged (the transmitter-dead rule uses the same floor)
MOTION_TICKS = (2, 3)  # motion in at least 2 of the last 3 ticks (anti-flicker)

USABLE_STATES = ("motion", "quiet")
LABELS = {"MOTION": "MOTION", "POSSIBLE": "POSSIBLE", "UNKNOWN": "UNKNOWN", "NO_DETECTION": "NO DETECTION"}


@dataclass(frozen=True)
class LinkReading:
    """One receiver at one tick, from the viewer's NodeView plus its heartbeat."""

    node_id: str
    state: str  # motion | quiet | weak | nosignal | warming
    score: float | None  # activity / motion threshold: >= 1 is motion
    hb_age: float | None  # seconds since the last heartbeat; None = never
    pps: int | None  # heartbeat measured_pps

    def online(self) -> bool:
        return self.hb_age is not None and self.hb_age <= HB_OFFLINE_S

    def usable(self) -> bool:
        return self.online() and self.state in USABLE_STATES and (self.pps or 0) >= PPS_MIN

    def healthy(self) -> bool:
        return self.usable() and self.hb_age is not None and self.hb_age <= HB_DEGRADED_S


@dataclass
class RoomTrack:
    room_id: str
    state: str = "UNKNOWN"
    last_evidence: float | None = None  # last motion evidence (wall seconds)
    last_known_state: str | None = None
    unusable_since: float | None = None  # first tick with no usable link
    usable_since: float | None = None  # first tick of the current usable run
    quiet_since: float | None = None  # all links healthy + quiet since
    calibrated: bool = False  # some link has learned its quiet baseline
    motion_hist: deque[bool] = field(default_factory=lambda: deque(maxlen=MOTION_TICKS[1]))


def band(pct: int) -> str:
    return "high" if pct >= 80 else "medium" if pct >= 50 else "low"


def _quality(readings: list[LinkReading]) -> float:
    used = [r for r in readings if r.usable()]
    if not used:
        return 0.0
    return sum(min(1.0, (r.pps or 0) / PPS_NOMINAL) for r in used) / len(used)


def _link_health(readings: list[LinkReading]) -> str:
    if not readings or not any(r.online() for r in readings):
        return "offline"
    if any(r.online() and (r.pps or 0) < PPS_MIN for r in readings):
        return "tx_dead"
    if all(r.healthy() for r in readings):
        return "ok"
    return "degraded"


def update(track: RoomTrack, readings: list[LinkReading], now: float, hold_s: float = HOLD_S) -> dict[str, Any]:
    """Advance one room by one tick and return its room_states entry (parent design shape)."""
    usable = [r for r in readings if r.usable()]
    if any(r.state in USABLE_STATES for r in readings):
        track.calibrated = True

    if not track.calibrated:
        return _entry(track, "UNKNOWN", 0, readings, calibrated=False)

    if not usable:
        if track.unusable_since is None:
            track.unusable_since = now
        track.usable_since = None
        track.quiet_since = None
        track.motion_hist.clear()
        if track.state != "UNKNOWN":
            track.last_known_state = track.state
        track.state = "UNKNOWN"
        age = int(now - track.unusable_since)
        return _entry(track, "UNKNOWN", 0, readings, stale=True, stale_age=age)

    if track.usable_since is None:
        track.usable_since = now
    if track.unusable_since is not None:  # coming back: 10 s of usable links first (Req 19.6)
        if now - track.usable_since < RECOVERY_S:
            return _entry(track, "UNKNOWN", 0, readings, stale=False)
        track.unusable_since = None

    track.motion_hist.append(any(r.state == "motion" for r in usable))
    motion_ev = sum(track.motion_hist) >= MOTION_TICKS[0]

    all_quiet = bool(readings) and all(r.healthy() and r.state == "quiet" for r in readings)
    if all_quiet:
        if track.quiet_since is None:
            track.quiet_since = now
    else:
        track.quiet_since = None

    if track.motion_hist[-1]:
        track.last_evidence = now  # only a tick that really saw motion counts as evidence
    if motion_ev:
        track.state = "MOTION"
    elif track.last_evidence is not None and now - track.last_evidence < hold_s:
        track.state = "POSSIBLE"  # moved, now still: hold (Req 8.6)
    elif track.state == "MOTION":
        track.state = "POSSIBLE"  # never MOTION -> NO_DETECTION
    elif track.quiet_since is not None and now - track.quiet_since >= hold_s:
        track.state = "NO_DETECTION"
    else:
        track.state = "POSSIBLE"  # not watched quietly for long enough: bias to presence (Req 6.5)

    track.last_known_state = track.state
    return _entry(track, track.state, _confidence(track, usable, readings, now, hold_s), readings)


def _confidence(track: RoomTrack, usable: list[LinkReading], readings: list[LinkReading], now: float,
                hold_s: float) -> int:
    if track.state == "MOTION":
        top = max((r.score or 0.0) for r in usable)
        base = 60 + 15 * min(2.0, max(0.0, top - 1.0))  # 60 at the threshold, 90 at 3x
    elif track.state == "POSSIBLE":
        if track.last_evidence is None:
            base = 50.0
        else:  # fades from 75 toward 50 over the hold
            base = 75 - 25 * min(1.0, (now - track.last_evidence) / hold_s)
    else:  # NO_DETECTION: grows with how long every link has been quiet beyond the hold
        quiet = now - (track.quiet_since or now)
        base = 55 + 35 * min(1.0, max(0.0, quiet - hold_s) / hold_s)
    pct = int(round(base * _quality(readings)))
    if any(r.online() and not r.healthy() for r in readings):
        pct = min(pct, 49)  # a late heartbeat or weak link forces low (Req 8.11)
    return max(0, min(100, pct))


def _entry(track: RoomTrack, state: str, pct: int, readings: list[LinkReading], *, calibrated: bool = True,
           stale: bool = False, stale_age: int | None = None) -> dict[str, Any]:
    pct = 0 if state == "UNKNOWN" else pct
    ev = None if track.last_evidence is None else float(math.floor(track.last_evidence))
    return {
        "room_id": track.room_id,
        "state": state,
        "label": LABELS[state],
        "confidence_band": band(pct),
        "confidence_pct": pct,
        "last_seen": ev,  # shown as "Motion last seen": the last motion evidence, not the last packet
        "last_evidence": ev,
        "stale": stale,
        "last_known_state": track.last_known_state if stale else None,
        "stale_age_s": stale_age,
        "calibrated": calibrated,
        "searched": False,
        "annotation": None,
        "alarm_time_state": None,
        "link_health": _link_health(readings),
        "source": "hub",
        "model_ver": None,
    }
