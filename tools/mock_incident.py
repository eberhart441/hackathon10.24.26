"""Scripted incident State_Source for the mock hub (pwa-dashboard Req 21).

`ScriptedIncident` implements `hub.web.source.StateSource` and plays the design
timeline (t = seconds since `trigger_alarm`):

    R1  MOTION high 86 (t < 15), then POSSIBLE medium 64
    R2  NO_DETECTION (t < 18), MOTION (18-30), POSSIBLE (30-55),
        RX2 degraded from 48, offline from 55 -> UNKNOWN, stale, last known POSSIBLE
    E1  in R1 (0-12), near R1/R2 low (12-18), in R2 (18-30), silent from 30,
        hollow marker and tag fault from 40
    F2  simulated rooms (if the floor plan has them) hold plausible states

Every `room_states` message carries `simulated: true`. Shapes match
hub/web/messages.py and dashboard/src/ws/messages.ts exactly.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any, NamedTuple

from hub.web.messages import label_for

__all__ = [
    "PlanRoom",
    "PlanNode",
    "ScriptedIncident",
    "rank",
    "rooms_from_floorplan",
    "nodes_from_floorplan",
]

STATE_ORDER = {"MOTION": 0, "POSSIBLE": 1, "UNKNOWN": 2, "NO_DETECTION": 3}

# Timeline marks (seconds since alarm).
T_R1_POSSIBLE = 15.0
T_E1_NEAR = 12.0
T_E1_IN_R2 = 18.0
T_R2_POSSIBLE = 30.0
T_E1_HOLLOW = 40.0
T_R2_LAST_EVIDENCE = 45.0
T_RX2_DEGRADED = 48.0
T_RX2_OFFLINE = 55.0

TAG_ID = "E1"


class PlanRoom(NamedTuple):
    room_id: str
    floor_id: str
    simulated: bool


class PlanNode(NamedTuple):
    node_id: str
    role: str  # "TX" | "RX"
    room_id: str


def rooms_from_floorplan(plan: Mapping[str, Any]) -> list[PlanRoom]:
    """(room_id, floor_id, simulated) for every room in the floor plan JSON, in plan order."""
    out: list[PlanRoom] = []
    for floor in plan.get("floors", []):
        for room in floor.get("rooms", []):
            out.append(PlanRoom(str(room["id"]), str(floor["id"]), bool(room.get("simulated", False))))
    return out


def nodes_from_floorplan(plan: Mapping[str, Any]) -> list[PlanNode]:
    """(node_id, role, room_id) for every node in the floor plan JSON."""
    return [PlanNode(str(n["id"]), str(n["role"]), str(n["room"])) for n in plan.get("nodes", [])]


def rank(rooms: Iterable[Mapping[str, Any]]) -> list[str]:
    """Search_Priority order (parent R9): unsearched before searched; within each group
    MOTION > POSSIBLE > UNKNOWN > NO_DETECTION, ties by more recent `last_seen`
    (None is oldest), remaining ties keep input order."""

    def key(r: Mapping[str, Any]) -> tuple[bool, int, float]:
        seen = r.get("last_seen")
        return (bool(r["searched"]), STATE_ORDER[r["state"]], -seen if seen is not None else float("inf"))

    return [r["room_id"] for r in sorted(rooms, key=key)]  # sorted() is stable


def _default_nodes(rooms: list[PlanRoom]) -> list[PlanNode]:
    nodes: list[PlanNode] = []
    for i, r in enumerate((r for r in rooms if not r.simulated), start=1):
        nodes += [PlanNode(f"TX{i}", "TX", r.room_id), PlanNode(f"RX{i}", "RX", r.room_id)]
    return nodes


# Plausible fixed states for simulated rooms, cycled in plan order:
# (state, band, pct, calibrated)
_SIMULATED_STATES = [
    ("POSSIBLE", "medium", 58.0, True),
    ("NO_DETECTION", "high", 81.0, True),
    ("UNKNOWN", "low", 0.0, False),
]


class ScriptedIncident:
    """Scripted State_Source. `clock` is the monotonic clock the hub passes as `now`."""

    def __init__(
        self,
        plan_rooms: Iterable[PlanRoom | tuple[str, str, bool]] | Mapping[str, str],
        clock: Callable[[], float] = time.monotonic,
        nodes: Iterable[PlanNode | tuple[str, str, str]] | None = None,
    ) -> None:
        if isinstance(plan_rooms, Mapping):
            rooms = [PlanRoom(rid, fid, False) for rid, fid in plan_rooms.items()]
        else:
            rooms = [PlanRoom(*r) for r in plan_rooms]
        self._rooms = rooms
        self._floor_of = {r.room_id: r.floor_id for r in rooms}
        self._floors = list(dict.fromkeys(r.floor_id for r in rooms))
        self._nodes = [PlanNode(*n) for n in nodes] if nodes is not None else _default_nodes(rooms)
        self._clock = clock
        # `now` is monotonic; the dashboard wants epoch seconds for last_seen/last_evidence.
        self._epoch_offset = time.time() - clock()
        self._alarm_at: float | None = None
        self._searched: set[str] = set()

    # --- StateSource -----------------------------------------------------

    def room_ids(self) -> set[str]:
        return set(self._floor_of)

    def trigger_alarm(self, now: float) -> dict:
        if self._alarm_at is None:
            self._alarm_at = now
            self._searched.clear()
        return {"system_state": "ALARM_ACTIVE", "simulated": True}

    def end_incident(self, now: float) -> dict:
        self._alarm_at = None
        self._searched.clear()
        return {"system_state": "IDLE"}

    def mark_searched(self, room_id: str, now: float) -> None:
        if room_id in self._floor_of:
            self._searched.add(room_id)

    def snapshot(self, now: float) -> list[dict]:
        ts = self._epoch(now)
        if self._alarm_at is None:
            return [
                {"type": "room_states", "ts": ts, "system_state": "IDLE", "simulated": True, "rooms": [], "ranking": []},
                self._health(ts, None),
                {"type": "recording", "ts": ts, "indicator": "Not recording", "stored_samples": 0, "fault": None},
            ]
        t = max(0.0, now - self._alarm_at)
        rooms = [self._room(r, t) for r in self._rooms]
        return [
            {
                "type": "room_states",
                "ts": ts,
                "system_state": "ALARM_ACTIVE",
                "simulated": True,
                "rooms": rooms,
                "ranking": rank(rooms),
            },
            self._health(ts, t),
            self._crew(ts, t),
            {
                "type": "recording",
                "ts": ts,
                "indicator": "Recording (alarm)",
                "stored_samples": int(t * 100) * sum(1 for n in self._nodes if n.role == "RX"),
                "fault": None,
            },
        ]

    # --- timeline ----------------------------------------------------------

    def _epoch(self, mono: float) -> float:
        return round(mono + self._epoch_offset, 3)

    def _at(self, t: float) -> float:
        """Epoch seconds for alarm offset t."""
        assert self._alarm_at is not None
        return self._epoch(self._alarm_at + t)

    def _script(self, room: PlanRoom, t: float) -> dict:
        """State fields for a room at alarm offset t (no searched/alarm_time_state)."""
        now_e = self._at(t)
        base = {
            "last_seen": None,
            "last_evidence": now_e,
            "stale": False,
            "last_known_state": None,
            "stale_age_s": None,
            "calibrated": True,
            "annotation": None,
            "link_health": "ok",
            "source": "edge",
            "model_ver": 1,
        }
        rid = room.room_id
        if room.simulated:
            idx = [r.room_id for r in self._rooms if r.simulated].index(rid)
            state, band, pct, calibrated = _SIMULATED_STATES[idx % len(_SIMULATED_STATES)]
            base.update(source="hub", model_ver=None, calibrated=calibrated)
            if state == "POSSIBLE":
                base["last_seen"] = self._at(0.0) - 20.0
            if not calibrated:
                base["last_evidence"] = None
            return {**base, "state": state, "confidence_band": band, "confidence_pct": pct}

        if rid == "R1":
            if t < T_R1_POSSIBLE:
                ann = "responder_present" if t < T_E1_NEAR else None
                return {**base, "state": "MOTION", "confidence_band": "high", "confidence_pct": 86.0,
                        "last_seen": now_e, "annotation": ann}
            ann = "recent_motion_may_be_responder" if t >= T_E1_IN_R2 else None
            return {**base, "state": "POSSIBLE", "confidence_band": "medium", "confidence_pct": 64.0,
                    "last_seen": self._at(T_R1_POSSIBLE), "annotation": ann}

        if rid == "R2":
            if t < T_E1_IN_R2:
                return {**base, "state": "NO_DETECTION", "confidence_band": "medium", "confidence_pct": 62.0}
            if t < T_R2_POSSIBLE:
                return {**base, "state": "MOTION", "confidence_band": "high", "confidence_pct": 88.0,
                        "last_seen": now_e, "annotation": "responder_present"}
            last_seen = self._at(T_R2_POSSIBLE)
            if t < T_R2_LAST_EVIDENCE:
                return {**base, "state": "POSSIBLE", "confidence_band": "medium", "confidence_pct": 60.0,
                        "last_seen": last_seen, "annotation": "recent_motion_may_be_responder"}
            last_ev = self._at(T_R2_LAST_EVIDENCE)
            if t < T_RX2_OFFLINE:
                link = "degraded" if t >= T_RX2_DEGRADED else "ok"
                return {**base, "state": "POSSIBLE", "confidence_band": "low", "confidence_pct": 38.0,
                        "last_seen": last_seen, "last_evidence": last_ev, "link_health": link,
                        "annotation": "recent_motion_may_be_responder"}
            return {**base, "state": "UNKNOWN", "confidence_band": "low", "confidence_pct": 0.0,
                    "last_seen": last_seen, "last_evidence": last_ev, "stale": True,
                    "last_known_state": "POSSIBLE", "stale_age_s": round(t - T_R2_LAST_EVIDENCE, 1),
                    "link_health": "offline"}

        # Any other real room in the plan: steady, nothing detected.
        return {**base, "state": "NO_DETECTION", "confidence_band": "medium", "confidence_pct": 60.0}

    def _room(self, room: PlanRoom, t: float) -> dict:
        s = self._script(room, t)
        return {
            "room_id": room.room_id,
            "state": s["state"],
            "label": label_for(s["state"]),
            "confidence_band": s["confidence_band"],
            "confidence_pct": s["confidence_pct"],
            "last_seen": s["last_seen"],
            "last_evidence": s["last_evidence"],
            "stale": s["stale"],
            "last_known_state": s["last_known_state"],
            "stale_age_s": s["stale_age_s"],
            "calibrated": s["calibrated"],
            "searched": room.room_id in self._searched,
            "annotation": s["annotation"],
            "alarm_time_state": self._script(room, 0.0)["state"],  # frozen at t = 0
            "link_health": s["link_health"],
            "source": s["source"],
            "model_ver": s["model_ver"],
        }

    def _tag(self, t: float) -> dict:
        tag = {"tag_id": TAG_ID, "near_rooms": [], "you_are_here": False}
        if t < T_E1_NEAR:
            return {**tag, "location_kind": "room", "room_id": "R1", "confidence_band": "high",
                    "last_heard_s": 0.5, "marker": "solid"}
        if t < T_E1_IN_R2:
            return {**tag, "location_kind": "near", "room_id": None, "near_rooms": ["R1", "R2"],
                    "confidence_band": "low", "last_heard_s": 0.5, "marker": "solid"}
        if t < T_R2_POSSIBLE:
            return {**tag, "location_kind": "room", "room_id": "R2", "confidence_band": "high",
                    "last_heard_s": 0.5, "marker": "solid"}
        silent = round(t - T_R2_POSSIBLE, 1)
        hollow = t >= T_E1_HOLLOW
        return {**tag, "location_kind": "room", "room_id": "R2",
                "confidence_band": "low" if hollow else "medium",
                "last_heard_s": silent, "marker": "hollow" if hollow else "solid"}

    def _crew(self, ts: float, t: float) -> dict:
        tags = [self._tag(t)]
        counts = {f: 0 for f in self._floors}
        for tag in tags:
            rid = tag["room_id"] or (tag["near_rooms"][0] if tag["near_rooms"] else None)
            floor = self._floor_of.get(rid) if rid else None
            if floor is not None:
                counts[floor] += 1
        return {"type": "crew", "ts": ts, "tags": tags, "floor_crew_counts": counts}

    def _health(self, ts: float, t: float | None) -> dict:
        rx2_status = "ok"
        if t is not None and t >= T_RX2_OFFLINE:
            rx2_status = "offline"
        elif t is not None and t >= T_RX2_DEGRADED:
            rx2_status = "degraded"

        nodes: list[dict] = []
        for n in self._nodes:
            node: dict = {"node_id": n.node_id, "role": n.role, "room_id": n.room_id, "status": "ok"}
            if n.node_id == "RX2" and rx2_status == "degraded":
                node.update(status="degraded", measured_pps=35.0,
                            cause="RX2 is receiving far fewer packets than expected.",
                            action=f"Trust {n.room_id} less. Search it in person.")
            elif n.node_id == "RX2" and rx2_status == "offline":
                node.update(status="offline",
                            cause="RX2 stopped reporting.",
                            action=f"{n.room_id} is now UNKNOWN. Search it in person.")
            elif n.node_id == "TX2" and rx2_status == "offline":
                node.update(status="offline", inferred_from="RX2",
                            cause="Status inferred from RX2: no receiver can hear TX2.",
                            action=f"Search {n.room_id} in person.")
            elif n.role == "RX":
                node["measured_pps"] = 100.0
            nodes.append(node)

        tag_faults = []
        if t is not None and t >= T_E1_HOLLOW:
            tag_faults.append({"tag_id": TAG_ID, "last_room": "R2", "silent_s": round(t - T_R2_POSSIBLE, 1)})

        faults = sum(1 for n in nodes if n["status"] != "ok") + len(tag_faults)
        summary = "All sensors online" if faults == 0 else f"{faults} fault" + ("" if faults == 1 else "s")
        return {"type": "health", "ts": ts, "summary": summary, "nodes": nodes, "tag_faults": tag_faults}
