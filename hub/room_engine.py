"""Room state from live link readings (pure, injected clock).

This is the parent design's state engine (design.md, "Room-state model with Last_Evidence hold")
driven by the per-link activity heuristic in firmware/tools/beacon_hub/viewer.py, because no
trained classifier exists yet. The rules that keep it honest are the design's:

  - Four states only. MOTION never goes straight to NO_DETECTION; it passes through POSSIBLE.
  - After motion stops the room holds POSSIBLE for HOLD_S since the last evidence.
  - With no classifier there is no "empty, high confidence" reading. NO_DETECTION therefore needs
    every link of the room healthy and quiet, continuously, for HOLD_S. Quiet is never "empty".
  - A room with no usable link is UNKNOWN and stale (last known state + age), and stays UNKNOWN
    for RECOVERY_S after its links come back.
  - During an incident, motion seen once keeps the room flagged (POSSIBLE, "Motion last seen")
    until the incident ends or a responder marks it searched: someone was there, which is exactly
    what crews need. Motion up to PRE_ALARM_S before the alarm counts (the rolling buffer).
  - confidence_pct is a presence likelihood: how likely it is that someone is in the room, from
    motion only. A quiet room that never showed motion sits at BASELINE_PCT (10) or below; MOTION is
    90-99; after motion it fades from 90 toward LATCH_FLOOR_PCT (50) and stays there. It is a
    heuristic, not a model probability, and a low number never means "empty".
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
PPS_MIN = 20  # below this the link is not judged (the transmitter-dead rule uses the same floor)
MOTION_TICKS = (2, 3)  # motion in at least 2 of the last 3 ticks (anti-flicker)
PRE_ALARM_S = 120.0  # motion this long before the alarm still latches the room (rolling buffer)
BASELINE_PCT = 10  # presence likelihood of a watched, quiet room with no motion: at most this
QUIET_PCT = 5  # ... after it has been quiet for a further HOLD_S
LATCH_FLOOR_PCT = 50  # a room that showed motion during the incident never drops below this

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
    fault: str | None = None  # why the viewer would leave this receiver out (glitching, clipping, ...)

    def online(self) -> bool:
        return self.hb_age is not None and self.hb_age <= HB_OFFLINE_S

    def usable(self) -> bool:
        return self.online() and self.state in USABLE_STATES and (self.pps or 0) >= PPS_MIN and self.fault is None

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


def _link_health(readings: list[LinkReading]) -> str:
    if not readings or not any(r.online() for r in readings):
        return "offline"
    if any(r.online() and (r.pps or 0) < PPS_MIN for r in readings):
        return "tx_dead"
    if all(r.healthy() for r in readings):
        return "ok"
    return "degraded"


def update(track: RoomTrack, readings: list[LinkReading], now: float, hold_s: float = HOLD_S,
           latch_after: float | None = None) -> dict[str, Any]:
    """Advance one room by one tick and return its room_states entry (parent design shape).

    latch_after: during an incident, the time from which motion latches the room (alarm time minus
    PRE_ALARM_S); None outside an incident, where the room returns to NO_DETECTION after the hold."""
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
    latched = latch_after is not None and track.last_evidence is not None and track.last_evidence >= latch_after
    if motion_ev:
        track.state = "MOTION"
    elif track.last_evidence is not None and now - track.last_evidence < hold_s:
        track.state = "POSSIBLE"  # moved, now still: hold (Req 8.6)
    elif track.state == "MOTION" or latched:
        track.state = "POSSIBLE"  # never MOTION -> NO_DETECTION; motion during the incident stays flagged
    elif track.quiet_since is not None and now - track.quiet_since >= hold_s:
        track.state = "NO_DETECTION"
    else:
        track.state = "POSSIBLE"  # not watched quietly for long enough: bias to presence (Req 6.5)

    track.last_known_state = track.state
    return _entry(track, track.state, presence_pct(track, usable, now, hold_s, latched), readings)


def presence_pct(track: RoomTrack, usable: list[LinkReading], now: float, hold_s: float, latched: bool) -> int:
    """How likely someone is in the room, 0-100, from motion only (see the module notes).

    Not scaled by packet rate or link health: a weak link must never make a room with motion look
    less occupied. Link problems are reported separately (link_health, UNKNOWN)."""
    if track.state == "MOTION":
        top = max((r.score or 0.0) for r in usable)
        return int(round(90 + 9 * min(1.0, max(0.0, top - 1.0) / 2.0)))  # 90 at the threshold, 99 at 3x
    if track.last_evidence is not None and (latched or now - track.last_evidence < hold_s):
        faded = 90 - (90 - LATCH_FLOOR_PCT) * min(1.0, (now - track.last_evidence) / hold_s)
        return int(round(faded))  # 90 right after motion, LATCH_FLOOR_PCT from the end of the hold on
    if track.state == "NO_DETECTION":
        quiet = now - (now if track.quiet_since is None else track.quiet_since)
        extra = min(1.0, max(0.0, quiet - hold_s) / hold_s)
        return int(round(BASELINE_PCT - (BASELINE_PCT - QUIET_PCT) * extra))
    return BASELINE_PCT  # watched, no motion, not yet quiet for the whole hold


def unsensed_entry(room_id: str) -> dict[str, Any]:
    """A plan room with no receiver: UNKNOWN for the whole incident, never quiet (Req 6.5)."""
    entry = _entry(RoomTrack(room_id), "UNKNOWN", 0, [], calibrated=False)
    entry.update(annotation="no_sensors", link_health="none")
    return entry


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
