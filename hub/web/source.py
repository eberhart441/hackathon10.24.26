"""The pluggable State_Source the hub web layer reads from (Req 20.2).

The web layer obtains room states, health, crew, and recording data only
through this interface. The mock hub (`tools/mock_incident.py`) implements it
now; the real pipeline implements it later over the parent's State_Engine,
ranking, and system state machine.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["StateSource"]


@runtime_checkable
class StateSource(Protocol):
    def room_ids(self) -> set[str]:
        """Every room id the source knows (used for 404 on mark-searched)."""
        ...

    def snapshot(self, now: float) -> list[dict]:
        """Current `room_states`, `health`, `crew`, and `recording` messages (parent shapes).

        `health` must be included in every system state (Req 7.7).
        """
        ...

    def trigger_alarm(self, now: float) -> dict:
        """Enter ALARM_ACTIVE; returns `{"system_state": "ALARM_ACTIVE", "simulated": ...}`."""
        ...

    def end_incident(self, now: float) -> dict:
        """Return to IDLE; returns `{"system_state": "IDLE"}`."""
        ...

    def mark_searched(self, room_id: str, now: float) -> None:
        """Record a Searched_Mark for a known room id."""
        ...
