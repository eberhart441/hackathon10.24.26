"""Hub -> dashboard WebSocket message shapes (pwa-dashboard Req 7.1).

Mirrors the parent design's "Hub: Web Server" section and dashboard/src/ws/messages.ts.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

RoomStateValue = Literal["MOTION", "POSSIBLE", "UNKNOWN", "NO_DETECTION"]
StateLabel = Literal["MOTION", "POSSIBLE", "UNKNOWN", "NO DETECTION"]
Band = Literal["high", "medium", "low"]
SystemState = Literal["IDLE", "CALIBRATION", "TEST", "ALARM_ACTIVE"]
LinkHealth = Literal["ok", "degraded", "offline"]
Annotation = Literal["responder_present", "recent_motion_may_be_responder"]

_LABELS: dict[str, StateLabel] = {
    "MOTION": "MOTION",
    "POSSIBLE": "POSSIBLE",
    "UNKNOWN": "UNKNOWN",
    "NO_DETECTION": "NO DETECTION",
}


def label_for(state: RoomStateValue) -> StateLabel:
    """Display label for a room state: NO_DETECTION -> "NO DETECTION", others unchanged."""
    try:
        return _LABELS[state]
    except KeyError:
        raise ValueError(f"unknown room state: {state!r}") from None


class RoomEntry(TypedDict):
    room_id: str
    state: RoomStateValue
    label: StateLabel
    confidence_band: Band
    confidence_pct: float  # 0..100
    last_seen: float | None  # epoch seconds
    last_evidence: float | None  # epoch seconds
    stale: bool
    last_known_state: RoomStateValue | None
    stale_age_s: float | None
    calibrated: bool
    searched: bool
    annotation: Annotation | None
    alarm_time_state: RoomStateValue | None
    link_health: LinkHealth
    source: Literal["edge", "hub"]
    model_ver: int | None


class RoomStatesMsg(TypedDict):
    type: Literal["room_states"]
    ts: float
    system_state: SystemState
    simulated: bool
    rooms: list[RoomEntry]
    ranking: list[str]


class HealthNode(TypedDict):
    node_id: str
    role: Literal["TX", "RX"]
    room_id: str
    status: Literal["ok", "degraded", "offline", "tx_dead"]
    measured_pps: NotRequired[float]
    inferred_from: NotRequired[str]
    cause: NotRequired[str]
    action: NotRequired[str]


class TagFault(TypedDict):
    tag_id: str
    last_room: str
    silent_s: float


class HealthMsg(TypedDict):
    type: Literal["health"]
    ts: float
    summary: str
    nodes: list[HealthNode]
    tag_faults: list[TagFault]


class CrewTag(TypedDict):
    tag_id: str
    location_kind: Literal["room", "near", "between", "lost"]
    room_id: str | None
    near_rooms: list[str]
    confidence_band: Band
    last_heard_s: float
    marker: Literal["solid", "hollow"]
    you_are_here: bool


class CrewMsg(TypedDict):
    type: Literal["crew"]
    ts: float
    tags: list[CrewTag]
    floor_crew_counts: dict[str, int]


class RecordingMsg(TypedDict):
    type: Literal["recording"]
    ts: float
    indicator: str
    stored_samples: int
    fault: str | None


HubMessage = RoomStatesMsg | HealthMsg | CrewMsg | RecordingMsg
