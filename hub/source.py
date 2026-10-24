"""The pluggable state source behind the web layer.

The real pipeline and the mock hub each provide a StateSource. The web layer
only reads messages through `latest()`/`subscribe()` and forwards commands.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, runtime_checkable

Message = dict[str, Any]
MESSAGE_TYPES = ("room_states", "health", "crew", "recording")


@runtime_checkable
class StateSource(Protocol):
    def latest(self) -> dict[str, Message]: ...
    def subscribe(self) -> asyncio.Queue[Message]: ...
    def unsubscribe(self, queue: asyncio.Queue[Message]) -> None: ...
    def room_ids(self) -> set[str]: ...
    async def trigger_alarm(self) -> Message: ...
    async def end_incident(self) -> Message: ...
    async def mark_searched(self, room_id: str) -> None: ...  # KeyError if unknown
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class Broadcaster:
    """Fan-out of published messages to subscriber queues, keeping the latest of each type."""

    def __init__(self) -> None:
        self._latest: dict[str, Message] = {}
        self._subs: set[asyncio.Queue[Message]] = set()

    def latest(self) -> dict[str, Message]:
        return dict(self._latest)

    def subscribe(self) -> asyncio.Queue[Message]:
        q: asyncio.Queue[Message] = asyncio.Queue(maxsize=256)
        self._subs.add(q)
        return q

    def unsubscribe(self, queue: asyncio.Queue[Message]) -> None:
        self._subs.discard(queue)

    def publish(self, msg: Message) -> None:
        self._latest[msg["type"]] = msg
        for q in list(self._subs):
            if q.full():  # slow client: drop its oldest message rather than block everyone
                q.get_nowait()
            q.put_nowait(msg)
