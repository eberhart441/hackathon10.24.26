"""FastAPI app for the hub web layer (design: "Hub: routes", Req 2, 3, 5, 6.1, 20).

`create_app(source, settings, clock)` wires the auth primitives, the
State_Source, and the Broadcaster into HTTP routes, the `/ws` socket, and the
static PWA shell. Laptop-only actions (alarm trigger, End incident, pairing
code, revoke) are gated on the socket peer being loopback, checked before the
token, so a phone gets 403 even with a valid token (Req 5.1).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import HTTPConnection

from hub.web.auth import Clock, PairingManager, RateLimiter, TokenStore, is_loopback
from hub.web.broadcast import Broadcaster
from hub.web.settings import Settings
from hub.web.source import StateSource

__all__ = ["create_app", "WS_AUTH_FAILED"]

WS_AUTH_FAILED = 4401
TokenKind = Literal["phone", "local"]


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    value = value.strip()
    return value or None


def create_app(
    source: StateSource,
    settings: Settings,
    clock: Clock = time.monotonic,
    *,
    ws_auth_timeout_s: float = 5.0,
    broadcast_period_s: float = 1.0,
) -> FastAPI:
    tokens = TokenStore(settings.secrets_file)
    pairing = PairingManager(clock)
    limiter = RateLimiter(clock)
    broadcaster = Broadcaster(source, clock)
    # The test flag is honored only when nothing but loopback is listening.
    force_remote = settings.test_force_remote and bool(settings.bind_hosts) and all(
        is_loopback(h) for h in settings.bind_hosts
    )

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(broadcaster.run(period_s=broadcast_period_s))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.tokens = tokens
    app.state.pairing = pairing
    app.state.limiter = limiter
    app.state.broadcaster = broadcaster
    app.state.force_remote = force_remote

    # --- helpers ----------------------------------------------------------
    def is_laptop(conn: HTTPConnection) -> bool:
        """Loopback socket peer, unless the test flag strips it (never grants)."""
        host = conn.client.host if conn.client else None
        if not is_loopback(host):
            return False
        if force_remote and conn.headers.get("x-test-remote") == "1":
            return False
        return True

    def require_laptop(request: Request) -> None:
        if not is_laptop(request):
            raise HTTPException(403, "This action is only available on the hub laptop")

    def require_token(request: Request) -> TokenKind:
        kind = tokens.valid(_bearer(request))
        if kind is None:
            raise HTTPException(401, "Missing or invalid token")
        return kind

    def require_laptop_token(request: Request) -> TokenKind:
        require_laptop(request)  # first: non-loopback always gets 403
        return require_token(request)

    # --- middleware and errors ---------------------------------------------
    @app.middleware("http")
    async def no_store_on_api(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/") or request.url.path == "/api":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            {"error": str(exc.detail)}, status_code=exc.status_code, headers=exc.headers
        )

    # --- local (laptop) routes --------------------------------------------
    @app.post("/api/local/token", dependencies=[Depends(require_laptop)])
    async def local_token() -> dict:
        return {"token": tokens.issue_local()}

    @app.get("/api/local/pairing-code", dependencies=[Depends(require_laptop_token)])
    async def pairing_code() -> dict:
        code, expires_in_s = pairing.new_code()
        return {"code": code, "expires_in_s": expires_in_s}

    @app.post("/api/local/revoke-phones", dependencies=[Depends(require_laptop_token)])
    async def revoke_phones() -> dict:
        tokens.revoke_phones()
        closed = await broadcaster.close_kind("phone", WS_AUTH_FAILED)
        return {"revoked": True, "closed_sockets": closed}

    # --- pairing ------------------------------------------------------------
    @app.post("/api/pair")
    async def pair(request: Request) -> dict:
        client = request.client.host if request.client else "unknown"
        if not limiter.allow(client):  # before reading the code (Req 2.4)
            raise HTTPException(429, "Too many pairing attempts")
        try:
            body = json.loads(await request.body())
        except ValueError:
            body = None
        code = body.get("code") if isinstance(body, dict) else None
        if not isinstance(code, str) or not pairing.redeem(code):
            raise HTTPException(401, "Wrong or expired code")
        return {"token": tokens.issue_phone()}

    # --- data routes --------------------------------------------------------
    @app.get("/api/whoami", dependencies=[Depends(require_token)])
    async def whoami(request: Request) -> dict:
        return {"laptop": is_laptop(request)}

    @app.get("/api/floorplan", dependencies=[Depends(require_token)])
    async def floorplan() -> Response:
        path: Path = settings.floorplan_file
        try:
            content = path.read_bytes()  # read per request (Req 6.1)
        except OSError:
            return JSONResponse(
                {"error": f"Floor plan file could not be read: {path}"}, status_code=500
            )
        return Response(content, media_type="application/json")

    @app.post("/api/alarm/trigger", dependencies=[Depends(require_laptop_token)])
    async def alarm_trigger() -> dict:
        result = source.trigger_alarm(clock())
        await broadcaster.publish_now()
        return result

    @app.post("/api/incident/end", dependencies=[Depends(require_laptop_token)])
    async def incident_end() -> dict:
        result = source.end_incident(clock())
        await broadcaster.publish_now()
        return result

    @app.post("/api/rooms/{room_id}/searched", dependencies=[Depends(require_token)])
    async def mark_searched(room_id: str) -> dict:
        if room_id not in source.room_ids():
            raise HTTPException(404, "Unknown room")
        source.mark_searched(room_id, clock())
        await broadcaster.publish_now()  # immediate room_states (Req 5.7)
        return {"room_id": room_id, "searched": True}

    @app.api_route(
        "/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    )
    async def api_not_found(rest: str) -> None:
        raise HTTPException(404, "Not found")

    # --- WebSocket ----------------------------------------------------------
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        try:
            first = await asyncio.wait_for(ws.receive(), ws_auth_timeout_s)
        except (asyncio.TimeoutError, RuntimeError):
            await _close(ws, WS_AUTH_FAILED)
            return
        if first.get("type") == "websocket.disconnect":
            return
        kind = _auth_kind(first.get("text"))
        if kind is None:
            await _close(ws, WS_AUTH_FAILED)
            return
        sock_kind: TokenKind = "local" if kind == "local" and is_laptop(ws) else "phone"
        broadcaster.register(ws, sock_kind)
        try:
            await broadcaster.publish_now()  # first snapshot without waiting a tick
            while True:
                try:
                    msg = await ws.receive()
                except RuntimeError:
                    break  # closed from our side (e.g. revoke)
                if msg.get("type") == "websocket.disconnect":
                    break
                command = _command(msg.get("text"))
                if command is None or sock_kind != "local":
                    continue  # phone sockets ignore commands (Req 5.2)
                if command == "trigger_alarm":
                    source.trigger_alarm(clock())
                else:
                    source.end_incident(clock())
                await broadcaster.publish_now()
        finally:
            broadcaster.unregister(ws)

    def _auth_kind(text: str | None) -> TokenKind | None:
        try:
            data = json.loads(text) if isinstance(text, str) else None
        except ValueError:
            return None
        if not isinstance(data, dict) or data.get("type") != "auth":
            return None
        token = data.get("token")
        return tokens.valid(token) if isinstance(token, str) else None

    # --- static PWA shell -----------------------------------------------------
    static_root = settings.static_dir.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> Response:
        if full_path == "ws" or full_path == "api" or full_path.startswith(("api/", "ws/")):
            raise HTTPException(404, "Not found")
        if full_path:
            candidate = (static_root / full_path).resolve()
            if candidate.is_relative_to(static_root) and candidate.is_file():
                return FileResponse(candidate)
            last = full_path.rsplit("/", 1)[-1]
            if full_path.startswith("assets/") or "." in last:
                raise HTTPException(404, "Not found")  # missing asset, not a route
        index = static_root / "index.html"
        if not index.is_file():
            raise HTTPException(404, "Dashboard not built")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


def _command(text: str | None) -> Literal["trigger_alarm", "end_incident"] | None:
    try:
        data = json.loads(text) if isinstance(text, str) else None
    except ValueError:
        return None
    kind = data.get("type") if isinstance(data, dict) else None
    return kind if kind in ("trigger_alarm", "end_incident") else None


async def _close(ws: WebSocket, code: int) -> None:
    with contextlib.suppress(Exception):
        await ws.close(code)
