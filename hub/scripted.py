"""Scripted mock incident (pure functions) for tools/mock_hub.py.

`build_frame` maps virtual seconds since the alarm to the four hub messages,
so the whole timeline can be tested without asyncio or real time. Every
`room_states` message carries `simulated: true`.

Timeline (virtual seconds after the alarm):
  R1  MOTION high until 25, then POSSIBLE medium (moving-then-still).
  R2  POSSIBLE; RX2 degraded 28-32; TX2 dead (RX2 pps collapse) 32-40;
      RX2 offline from 40. R2 is UNKNOWN and stale from 32.
  F2  R3 MOTION, R4 POSSIBLE low, R5 UNKNOWN uncalibrated, R6 NO_DETECTION.
  E1  room R1 high 0-20, between 20-24, near R1/R2 24-28, room R2 medium
      28-40, near R2/R1 low 40-80 (RX2 offline forces low), silent from 80
      (hollow marker and tag fault once 10 s silent).
"""

from __future__ import annotations

import math
from typing import Any

PRIORITY = {"MOTION": 1, "POSSIBLE": 2, "UNKNOWN": 3, "NO_DETECTION": 4}
LABELS = {"MOTION": "MOTION", "POSSIBLE": "POSSIBLE", "UNKNOWN": "UNKNOWN", "NO_DETECTION": "NO DETECTION"}
ROOM_IDS = ("R1", "R2", "R3", "R4", "R5", "R6")
ROOM_FLOOR = {"R1": "F1", "R2": "F1", "R3": "F2", "R4": "F2", "R5": "F2", "R6": "F2"}
TAG_LOST_S = 10

Msg = dict[str, Any]


def band(pct: int) -> str:
    return "high" if pct >= 80 else "medium" if pct >= 50 else "low"


def rank(rooms: list[Msg]) -> list[str]:
    """Parent design rank(): unsearched first, then priority, newer last_seen, room id."""
    return [
        r["room_id"]
        for r in sorted(
            rooms,
            key=lambda r: (
                bool(r["searched"]),
                PRIORITY[r["state"]],
                -(r["last_seen"] or 0.0),
                r["room_id"],
            ),
        )
    ]


class Clock:
    """Virtual timeline seconds -> wall-clock epoch seconds."""

    def __init__(self, alarm_ts: float, speed: float):
        self.alarm_ts = alarm_ts
        self.speed = speed

    def wall(self, vt: float) -> float:
        return self.alarm_ts + vt / self.speed

    def age(self, vt_from: float, vt_now: float) -> int:
        return max(0, int((vt_now - vt_from) / self.speed))


def _room(room_id: str, state: str, pct: int, *, last_seen, last_evidence, link="ok", calibrated=True,
          stale=False, last_known=None, stale_age=None, annotation=None, source="hub", model_ver=None) -> Msg:
    pct = 0 if state == "UNKNOWN" else pct
    return {
        "room_id": room_id,
        "state": state,
        "label": LABELS[state],
        "confidence_band": band(pct),
        "confidence_pct": pct,
        "last_seen": None if last_seen is None else float(math.floor(last_seen)),
        "last_evidence": None if last_evidence is None else float(math.floor(last_evidence)),
        "stale": stale,
        "last_known_state": last_known,
        "stale_age_s": stale_age,
        "calibrated": calibrated,
        "searched": False,
        "annotation": annotation,
        "alarm_time_state": None,
        "link_health": link,
        "source": source,
        "model_ver": model_ver,
    }


def tag_phase(vt: float) -> tuple[str, str | None, list[str], int]:
    """(location_kind, room_id, near_rooms, confidence_pct) for tag E1 while audible."""
    if vt < 20:
        return "room", "R1", [], 90
    if vt < 24:
        return "between", None, ["R1", "R2"], 30
    if vt < 28:
        return "near", None, ["R1", "R2"], 40
    if vt < 40:
        return "room", "R2", [], 70
    return "near", None, ["R2", "R1"], 35


def room_list(vt: float, c: Clock) -> list[Msg]:
    now = c.wall(vt)
    e1_kind, e1_room, _, e1_pct = tag_phase(vt)
    e1_in_r1 = vt < 80 and e1_kind == "room" and e1_room == "R1" and e1_pct >= 50

    # R1: edge-mode room, moving then still.
    if vt < 25:
        r1 = _room("R1", "MOTION", 88, last_seen=now, last_evidence=now, source="edge", model_ver=3,
                   annotation="responder_present" if e1_in_r1 else None)
    else:
        r1 = _room("R1", "POSSIBLE", 62, last_seen=now, last_evidence=c.wall(25), source="edge", model_ver=3,
                   annotation="recent_motion_may_be_responder")

    # R2: possible presence, then its link fails.
    r2_evidence = c.wall(0) - 10
    if vt < 28:
        r2 = _room("R2", "POSSIBLE", 71, last_seen=now, last_evidence=r2_evidence)
    elif vt < 32:
        r2 = _room("R2", "POSSIBLE", 45, last_seen=now, last_evidence=r2_evidence, link="degraded")
    else:
        r2 = _room("R2", "UNKNOWN", 0, last_seen=c.wall(32), last_evidence=r2_evidence,
                   link="tx_dead" if vt < 40 else "offline", stale=True, last_known="POSSIBLE",
                   stale_age=c.age(32, vt))

    r3 = _room("R3", "MOTION", 84, last_seen=now, last_evidence=now)
    r4 = _room("R4", "POSSIBLE", 38, last_seen=now, last_evidence=c.wall(0) - 30)
    r5 = _room("R5", "UNKNOWN", 0, last_seen=None, last_evidence=None, calibrated=False)
    r6 = _room("R6", "NO_DETECTION", 86, last_seen=now, last_evidence=None)
    return [r1, r2, r3, r4, r5, r6]


def health_msg(vt: float | None, c: Clock | None, now: float) -> Msg:
    """Node health. vt is None in IDLE (all healthy, no tag processing)."""
    rx1 = {"node_id": "RX1", "role": "RX", "room_id": "R1", "status": "ok", "measured_pps": 98}
    rx2 = {"node_id": "RX2", "role": "RX", "room_id": "R2", "status": "ok", "measured_pps": 97}
    tx1 = {"node_id": "TX1", "role": "TX", "room_id": "R1", "status": "ok", "inferred_from": "RX1"}
    tx2 = {"node_id": "TX2", "role": "TX", "room_id": "R2", "status": "ok", "inferred_from": "RX2"}
    tag_faults: list[Msg] = []
    if vt is not None:
        if 28 <= vt < 32:
            rx2.update(status="degraded", cause="RX2 heartbeat late (over 3 s)", action="Check RX2 USB cable and power")
        elif 32 <= vt < 40:
            rx2["measured_pps"] = 9
            tx2.update(status="tx_dead", cause="RX2 measured packet rate below 20% for 5 s", action="Check TX2 power")
        elif vt >= 40:
            rx2.update(status="offline", measured_pps=0, cause="No RX2 heartbeat for 10 s",
                       action="Check RX2 power and USB cable")
            tx2.update(status="offline", cause="TX2 cannot be checked while RX2 is offline", action="Restore RX2 first")
        silent = c.age(80, vt) if vt >= 80 else 0
        if vt >= 80 and silent >= TAG_LOST_S:
            tag_faults.append({"tag_id": "E1", "last_room": "R2", "silent_s": silent})
    nodes = [rx1, rx2, tx1, tx2]
    faults = sum(n["status"] != "ok" for n in nodes) + len(tag_faults)
    summary = "All sensors online" if faults == 0 else f"{faults} fault" + ("s" if faults > 1 else "")
    return {"type": "health", "ts": now, "summary": summary, "nodes": nodes, "tag_faults": tag_faults}


def crew_msg(vt: float, c: Clock) -> Msg:
    now = c.wall(vt)
    if vt >= 80:
        silent = c.age(80, vt)
        if silent >= TAG_LOST_S:
            tag = {"tag_id": "E1", "location_kind": "lost", "room_id": "R2", "near_rooms": [],
                   "confidence_band": "low", "last_heard_s": silent, "marker": "hollow", "you_are_here": False}
        else:
            tag = {"tag_id": "E1", "location_kind": "near", "room_id": None, "near_rooms": ["R2", "R1"],
                   "confidence_band": "low", "last_heard_s": silent, "marker": "solid", "you_are_here": False}
    else:
        kind, room, near, pct = tag_phase(vt)
        tag = {"tag_id": "E1", "location_kind": kind, "room_id": room, "near_rooms": near,
               "confidence_band": band(pct), "last_heard_s": 0, "marker": "solid", "you_are_here": False}
    counts: dict[str, int] = {}
    if tag["location_kind"] != "lost":
        rooms = [tag["room_id"]] if tag["room_id"] else tag["near_rooms"]
        floors = {ROOM_FLOOR[r] for r in rooms}
        if len(floors) == 1:
            f = floors.pop()
            counts[f] = counts.get(f, 0) + 1
    return {"type": "crew", "ts": now, "tags": [tag], "floor_crew_counts": counts}


def build_frame(vt: float, c: Clock, searched: set[str], snapshot: dict[str, str]) -> dict[str, Msg]:
    """All four messages at virtual time vt after the alarm."""
    now = c.wall(vt)
    rooms = room_list(vt, c)
    for r in rooms:
        r["searched"] = r["room_id"] in searched
        r["alarm_time_state"] = snapshot.get(r["room_id"])
    return {
        "room_states": {"type": "room_states", "ts": now, "system_state": "ALARM_ACTIVE", "simulated": True,
                        "rooms": rooms, "ranking": rank(rooms)},
        "health": health_msg(vt, c, now),
        "crew": crew_msg(vt, c),
        "recording": {"type": "recording", "ts": now, "indicator": "Recording (alarm)",
                      "stored_samples": len(rooms) * (1 + int(vt / c.speed)), "fault": None},
    }


def alarm_snapshot(c: Clock) -> dict[str, str]:
    return {r["room_id"]: r["state"] for r in room_list(0.0, c)}


def idle_frame(now: float) -> dict[str, Msg]:
    """IDLE: health only; no occupancy, no crew, nothing stored."""
    return {
        "room_states": {"type": "room_states", "ts": now, "system_state": "IDLE", "simulated": True,
                        "rooms": [], "ranking": []},
        "health": health_msg(None, None, now),
        "crew": {"type": "crew", "ts": now, "tags": [], "floor_crew_counts": {}},
        "recording": {"type": "recording", "ts": now, "indicator": "Not recording", "stored_samples": 0, "fault": None},
    }
