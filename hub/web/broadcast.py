"""WebSocket broadcast of State_Source snapshots (Req 7.7, 14.1, 20.2, 20.3).

Framework-light: sockets are anything with an async `send_text(str)` and an
async `close(code)`, which FastAPI's `WebSocket` satisfies and test fakes can
implement in a few lines.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol

from hub.web.auth import Clock
from hub.web.source import StateSource

__all__ = ["redact_for_wire", "WireSocket", "SocketKind", "Broadcaster"]

SocketKind = Literal["phone", "local"]
Sleep = Callable[[float], Awaitable[None]]


class WireSocket(Protocol):
    async def send_text(self, data: str) -> None: ...
    async def close(self, code: int = 1000) -> None: ...


def redact_for_wire(msg: dict, system_state: str | None = None) -> dict:
    """Pure. Returns a new dict; never mutates `msg`.

    - `room_states` with `system_state` IDLE -> `rooms: []` and `ranking: []` (Req 14.1).
    - `crew` while the system state is IDLE -> `tags: []` and `floor_crew_counts: {}`.
      `crew` carries no system state of its own, so the caller passes it via
      `system_state`; when omitted, crew passes through unchanged.
    - Every other message passes through unchanged (as a shallow copy).
    """
    out = dict(msg)
    kind = msg.get("type")
    if kind == "room_states" and msg.get("system_state") == "IDLE":
        out["rooms"] = []
        out["ranking"] = []
    elif kind == "crew" and system_state == "IDLE":
        out["tags"] = []
        out["floor_crew_counts"] = {}
    return out


class Broadcaster:
    """Sends redacted State_Source snapshots to every registered socket.

    `run()` publishes once per `period_s` (1 Hz by default) in every system
    state, so `health` goes out at least once per second (Req 7.7).
    `publish_now()` pushes an immediate snapshot after commands (Req 5.7, 20.3).
    A socket whose send fails or times out is dropped; the others still get
    the message.
    """

    def __init__(
        self,
        source: StateSource | None = None,
        clock: Clock | None = None,
        sleep: Sleep = asyncio.sleep,
        send_timeout_s: float = 1.0,
    ) -> None:
        self._source = source
        self._clock = clock
        self._sleep = sleep
        self._send_timeout_s = send_timeout_s
        self._sockets: dict[WireSocket, SocketKind] = {}
        self._lock = asyncio.Lock()
        # crew messages carry no system_state; until a room_states says otherwise,
        # assume IDLE so crew is redacted (fail closed).
        self._system_state = "IDLE"

    # --- registration -------------------------------------------------
    def register(self, socket: WireSocket, kind: SocketKind) -> None:
        if kind not in ("phone", "local"):
            raise ValueError(f"unknown socket kind: {kind!r}")
        self._sockets[socket] = kind

    def unregister(self, socket: WireSocket) -> None:
        self._sockets.pop(socket, None)

    def kind_of(self, socket: WireSocket) -> SocketKind | None:
        return self._sockets.get(socket)

    @property
    def sockets(self) -> dict[WireSocket, SocketKind]:
        return dict(self._sockets)

    async def close_kind(self, kind: SocketKind, code: int = 1000) -> int:
        """Close and unregister every socket of `kind` (revoke closes phones). Returns the count."""
        targets = [s for s, k in self._sockets.items() if k == kind]
        for s in targets:
            self._sockets.pop(s, None)
            try:
                await s.close(code)
            except Exception:
                pass  # already gone; it is unregistered either way
        return len(targets)

    # --- publishing ---------------------------------------------------
    def wire_messages(self, now: float) -> list[str]:
        """Snapshot -> redact_for_wire -> JSON strings, in snapshot order."""
        assert self._source is not None, "Broadcaster has no StateSource"
        msgs = self._source.snapshot(now)
        for m in msgs:
            if m.get("type") == "room_states" and isinstance(m.get("system_state"), str):
                self._system_state = m["system_state"]
        return [
            json.dumps(redact_for_wire(m, self._system_state), separators=(",", ":"))
            for m in msgs
        ]

    async def _send_all(self, socket: WireSocket, frames: list[str]) -> None:
        for frame in frames:
            await socket.send_text(frame)

    async def publish_now(self) -> None:
        """Send the current snapshot to every registered socket now."""
        assert self._clock is not None, "Broadcaster has no clock"
        async with self._lock:
            frames = self.wire_messages(self._clock())
            targets = list(self._sockets)
            if not targets or not frames:
                return
            results = await asyncio.gather(
                *(
                    asyncio.wait_for(self._send_all(s, frames), self._send_timeout_s)
                    for s in targets
                ),
                return_exceptions=True,
            )
            for s, r in zip(targets, results):
                if isinstance(r, BaseException):
                    self.unregister(s)

    async def run(
        self,
        source: StateSource | None = None,
        clock: Clock | None = None,
        period_s: float = 1.0,
    ) -> None:
        """Publish every `period_s` until cancelled, on a fixed schedule (no drift)."""
        if source is not None:
            self._source = source
        if clock is not None:
            self._clock = clock
        assert self._source is not None and self._clock is not None
        next_at = self._clock()
        while True:
            try:
                await self.publish_now()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass  # a bad snapshot must not stop health going out next tick
            next_at += period_s
            now = self._clock()
            if next_at < now:  # fell behind; skip missed ticks instead of bursting
                next_at = now
            await self._sleep(next_at - now)
