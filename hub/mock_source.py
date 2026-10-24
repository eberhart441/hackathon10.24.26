"""ScriptedSource: a StateSource that plays the scripted incident in hub/scripted.py."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Callable

from . import scripted
from .source import Broadcaster, Message


class ScriptedSource(Broadcaster):
    def __init__(self, speed: float = 1.0, clock: Callable[[], float] = time.time, tick_s: float = 1.0):
        super().__init__()
        self.speed = speed
        self._clock = clock
        self._tick_s = tick_s
        self._alarm: scripted.Clock | None = None
        self._snapshot: dict[str, str] = {}
        self._searched: set[str] = set()
        self._task: asyncio.Task | None = None

    # --- StateSource -------------------------------------------------------
    def room_ids(self) -> set[str]:
        return set(scripted.ROOM_IDS)

    async def start(self) -> None:
        self.publish_frame()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def trigger_alarm(self) -> Message:
        if self._alarm is None:  # idempotent while ALARM_ACTIVE
            self._alarm = scripted.Clock(self._clock(), self.speed)
            self._snapshot = scripted.alarm_snapshot(self._alarm)
            self._searched.clear()
            self.publish_frame()
        return {"system_state": "ALARM_ACTIVE", "simulated": True}

    async def end_incident(self) -> Message:
        self._alarm = None
        self._snapshot = {}
        self._searched.clear()
        self.publish_frame()
        return {"system_state": "IDLE", "simulated": True}

    async def mark_searched(self, room_id: str) -> None:
        if room_id not in scripted.ROOM_IDS:
            raise KeyError(room_id)
        if self._alarm is not None:  # searched marks only exist during an incident
            self._searched.add(room_id)
            self.publish_frame()

    # --- internals ---------------------------------------------------------
    def frame(self) -> dict[str, Message]:
        now = self._clock()
        if self._alarm is None:
            return scripted.idle_frame(now)
        vt = (now - self._alarm.alarm_ts) * self.speed
        return scripted.build_frame(vt, self._alarm, self._searched, self._snapshot)

    def publish_frame(self) -> None:
        for msg in self.frame().values():
            self.publish(msg)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._tick_s)
            self.publish_frame()
