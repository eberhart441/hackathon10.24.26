"""Room-level responder tag location from receiver TAG summaries (pure, injected clock).

Implements the parent design's "Tag localization algorithm" (design.md, Req 25, 27, 30):
an EWMA of RSSI per (tag, room); rooms that did not hear the tag this interval count as
-95 dBm; the located room only switches when a candidate leads it by 6 dB for 2 s, or when the
current room has not heard the tag for 3 s; confidence comes from the lead over every other room.

Honesty rules (Req 25.5-25.7): low confidence never resolves to a single room ("near" or
"between" instead), and a tag silent for 10 s becomes a hollow marker at the last room it was
heard in, never an extrapolated position. Location is a room, never a point.

The hub feeds summaries only while an incident (or test/calibration) is open; in IDLE they are
dropped before they get here (Req 29.2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

LEAD_DB = 6.0
LEAD_HOLD_S = 2.0
SILENCE_S = 3.0
LOST_S = 10.0
HIGH_LEAD_DB = 10.0
EWMA_TC_S = 2.0
FLOOR_DBM = -95.0
WEAK_DBM = -75.0
INTERVAL_S = 1.5


@dataclass
class TagTrack:
    ewma: dict[str, float] = field(default_factory=dict)  # room -> smoothed RSSI
    heard_at: dict[str, float] = field(default_factory=dict)  # room -> last time heard
    current: str | None = None
    lead_candidate: str | None = None
    lead_since: float | None = None


class TagLocator:
    def __init__(self, rooms: list[str]):
        self.rooms = list(rooms)
        self.tags: dict[str, TagTrack] = {}

    def reset(self) -> None:
        self.tags.clear()

    def on_summary(self, tag_id: str, room_id: str, mean_rssi: float, now: float) -> None:
        if room_id not in self.rooms:
            return
        t = self.tags.setdefault(tag_id, TagTrack())
        prev_t = t.heard_at.get(room_id)
        if room_id in t.ewma and prev_t is not None:
            alpha = 1 - math.exp(-max(0.0, now - prev_t) / EWMA_TC_S)
            t.ewma[room_id] += alpha * (mean_rssi - t.ewma[room_id])
        else:
            t.ewma[room_id] = mean_rssi
        t.heard_at[room_id] = now

    def _adjusted(self, t: TagTrack, room: str, now: float) -> float:
        heard = t.heard_at.get(room)
        if heard is None or now - heard > INTERVAL_S:
            return FLOOR_DBM
        return t.ewma[room]

    def locate(self, tag_id: str, now: float, degraded_rooms: set[str] = frozenset(),
               any_rx_offline: bool = False) -> dict:
        """The crew message entry for one tag (parent design shape)."""
        t = self.tags[tag_id]
        last_heard = max(t.heard_at.values())
        silent = now - last_heard
        if silent >= LOST_S:
            last_room = t.current or max(t.heard_at, key=t.heard_at.get)
            return _tag(tag_id, "lost", last_room, [], "low", silent, "hollow")

        adj = {r: self._adjusted(t, r, now) for r in self.rooms}
        cand = max(adj, key=lambda r: (adj[r], r == t.current))
        if t.current is None:
            t.current = cand
        elif cand != t.current:
            if adj[cand] - adj[t.current] >= LEAD_DB:
                if t.lead_candidate != cand:  # new candidate: restart the timer (Req 25.8)
                    t.lead_candidate, t.lead_since = cand, now
            else:
                t.lead_candidate, t.lead_since = None, None  # lead not continuous
            held = t.lead_candidate == cand and t.lead_since is not None and now - t.lead_since >= LEAD_HOLD_S
            cur_silent = now - t.heard_at.get(t.current, -math.inf) >= SILENCE_S
            if held or cur_silent:
                t.current, t.lead_candidate, t.lead_since = cand, None, None
        else:
            t.lead_candidate, t.lead_since = None, None

        cur = t.current
        others = [adj[r] for r in self.rooms if r != cur]
        lead = adj[cur] - max(others) if others else math.inf  # lead over EVERY other room
        if cur in degraded_rooms:
            band = "low"
        elif any_rx_offline and adj[cand] < WEAK_DBM:
            band = "low"  # Req 30.1
        elif lead >= HIGH_LEAD_DB:
            band = "high"
        elif lead >= LEAD_DB:
            band = "medium"
        else:
            band = "low"

        if band == "low":  # never a single room at low confidence (Req 25.5, 25.6)
            ranked = sorted(self.rooms, key=lambda r: adj[r], reverse=True)
            heard = [r for r in ranked if adj[r] > FLOOR_DBM]
            if len(heard) >= 2 and adj[ranked[0]] - adj[ranked[1]] < LEAD_DB:
                return _tag(tag_id, "between", None, ranked[:2], "low", silent, "solid")
            near = ranked[:2] if len(ranked) >= 2 else ranked[:1]
            return _tag(tag_id, "near", None, near, "low", silent, "solid")
        return _tag(tag_id, "room", cur, [], band, silent, "solid")

    def crew_message(self, now: float, room_floor: dict[str, str], degraded_rooms: set[str] = frozenset(),
                     any_rx_offline: bool = False) -> dict:
        tags = [self.locate(tag, now, degraded_rooms, any_rx_offline) for tag in sorted(self.tags)]
        counts: dict[str, int] = {}
        for t in tags:
            if t["location_kind"] == "lost":
                continue
            rooms = [t["room_id"]] if t["room_id"] else t["near_rooms"]
            floors = {room_floor[r] for r in rooms if r in room_floor}
            if len(floors) == 1:  # only count a crew member whose floor is certain
                f = floors.pop()
                counts[f] = counts.get(f, 0) + 1
        return {"type": "crew", "ts": now, "tags": tags, "floor_crew_counts": counts}

    def lost_faults(self, now: float) -> list[dict]:
        out = []
        for tag_id, t in sorted(self.tags.items()):
            silent = now - max(t.heard_at.values())
            if silent >= LOST_S:
                last_room = t.current or max(t.heard_at, key=t.heard_at.get)
                out.append({"tag_id": tag_id, "last_room": last_room, "silent_s": int(silent)})
        return out


def _tag(tag_id: str, kind: str, room: str | None, near: list[str], band: str, silent: float, marker: str) -> dict:
    return {
        "tag_id": tag_id,
        "location_kind": kind,
        "room_id": room,
        "near_rooms": near,
        "confidence_band": band,
        "last_heard_s": int(max(0.0, silent)),
        "marker": marker,
        "you_are_here": False,
    }
