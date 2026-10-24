"""FastAPI web layer: App_Shell, token-protected REST API, and the /ws push channel."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.websockets import WebSocketState

from .auth import Auth
from .source import MESSAGE_TYPES, StateSource

LOOPBACK_HOSTS = {"127.0.0.1", "::1"}
WS_AUTH_TIMEOUT_S = 5.0
WS_UNAUTHORIZED = 4401

HUB_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_DIR = HUB_DIR / "config"
DEFAULT_STATIC_DIR = HUB_DIR / "static"

NO_SHELL_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>RoomSense hub</title></head>
<body style="font-family:system-ui;background:#111;color:#eee;padding:24px">
<p><strong>Decision support only — does not replace a full search.</strong></p>
<p>The hub is running, but the dashboard has not been built yet.
Build it with <code>npm run build</code> in <code>dashboard/</code>; the output goes to <code>hub/static</code>.</p>
</body></html>"""


def default_is_loopback(host: str | None) -> bool:
    return host in LOOPBACK_HOSTS


def create_app(
    source: StateSource,
    *,
    config_dir: Path = DEFAULT_CONFIG_DIR,
    static_dir: Path = DEFAULT_STATIC_DIR,
    auth: Auth | None = None,
    is_loopback: Callable[[str | None], bool] = default_is_loopback,
) -> FastAPI:
    config_dir = Path(config_dir)
    static_dir = Path(static_dir).resolve()
    auth = auth or Auth(config_dir / "secrets.json")
    floorplan_path = config_dir / "floorplan.json"
    phone_sockets: set[WebSocket] = set()

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        await source.start()
        try:
            yield
        finally:
            await source.stop()

    app = FastAPI(title="RoomSense hub", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.auth = auth
    app.state.source = source

    @app.middleware("http")
    async def api_no_store(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # --- dependencies ------------------------------------------------------
    def client_host(request: Request) -> str | None:
        return request.client.host if request.client else None

    def require_token(request: Request) -> str:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not auth.valid(token.strip()):
            raise HTTPException(status_code=401, detail="Pairing token missing or not recognised")
        return token.strip()

    def require_loopback(request: Request) -> None:
        if not is_loopback(client_host(request)):
            raise HTTPException(status_code=403, detail="This control is only available on the hub laptop")

    # --- auth / pairing ----------------------------------------------------
    @app.get("/api/whoami")
    def whoami(request: Request, _t: str = Depends(require_token)):
        return {"loopback": is_loopback(client_host(request))}

    @app.post("/api/local/token", dependencies=[Depends(require_loopback)])
    def local_token():
        return {"token": auth.laptop_token()}

    @app.get("/api/local/pairing-code", dependencies=[Depends(require_loopback), Depends(require_token)])
    def pairing_code():
        code, ttl = auth.new_pairing_code()
        return {"code": code, "expires_in": ttl}

    @app.post("/api/pair")
    async def pair(request: Request):
        if auth.rate_limited(client_host(request) or "unknown"):
            return JSONResponse({"detail": "Too many attempts. Wait a minute and try again."}, status_code=429)
        try:
            body = await request.json()
            code = str(body.get("code", ""))
        except (ValueError, AttributeError):
            code = ""
        token = auth.pair(code)
        if token is None:
            return JSONResponse({"detail": "Code is wrong, expired, or already used"}, status_code=401)
        return {"token": token}

    @app.post("/api/local/revoke-phones", dependencies=[Depends(require_loopback), Depends(require_token)])
    async def revoke_phones():
        auth.revoke_phones()
        closed = 0
        for ws in list(phone_sockets):
            with contextlib.suppress(Exception):
                await ws.close(code=WS_UNAUTHORIZED)
                closed += 1
        phone_sockets.clear()
        return {"revoked": True, "closed_sockets": closed}

    # --- data --------------------------------------------------------------
    @app.get("/api/floorplan", dependencies=[Depends(require_token)])
    def floorplan():
        try:
            return JSONResponse(json.loads(floorplan_path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Floor plan file not found: {floorplan_path.name}")
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=f"Floor plan file is not valid JSON: {exc}")

    @app.post("/api/alarm/trigger", dependencies=[Depends(require_loopback), Depends(require_token)])
    async def trigger_alarm():
        return await source.trigger_alarm()

    @app.post("/api/incident/end", dependencies=[Depends(require_loopback), Depends(require_token)])
    async def end_incident():
        return await source.end_incident()

    @app.post("/api/rooms/{room_id}/searched", dependencies=[Depends(require_token)])
    async def mark_searched(room_id: str):
        if room_id not in source.room_ids():
            raise HTTPException(status_code=404, detail=f"Unknown room {room_id}")
        try:
            await source.mark_searched(room_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Unknown room {room_id}")
        return {"room_id": room_id, "searched": True}

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    def api_not_found(rest: str):
        raise HTTPException(status_code=404, detail="Not found")

    # --- websocket ---------------------------------------------------------
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        try:
            first = await asyncio.wait_for(ws.receive_text(), timeout=WS_AUTH_TIMEOUT_S)
            msg = json.loads(first)
            kind = auth.kind(msg.get("token")) if msg.get("type") == "auth" else None
        except (asyncio.TimeoutError, ValueError, AttributeError, WebSocketDisconnect):
            kind = None
        if kind is None:
            if ws.client_state == WebSocketState.CONNECTED:
                with contextlib.suppress(Exception):
                    await ws.close(code=WS_UNAUTHORIZED)
            return

        loopback = is_loopback(ws.client.host if ws.client else None)
        if kind == "phone":
            phone_sockets.add(ws)
        queue = source.subscribe()

        async def sender():
            latest = source.latest()
            for t in MESSAGE_TYPES:
                if t in latest:
                    await ws.send_json(latest[t])
            while True:
                await ws.send_json(await queue.get())

        async def receiver():
            while True:
                try:
                    cmd = json.loads(await ws.receive_text())
                except ValueError:
                    continue
                kind_ = cmd.get("type") if isinstance(cmd, dict) else None
                if kind_ == "mark_searched":
                    with contextlib.suppress(KeyError):
                        await source.mark_searched(str(cmd.get("room_id")))
                elif kind_ == "trigger_alarm" and loopback:
                    await source.trigger_alarm()
                elif kind_ == "end_incident" and loopback:
                    await source.end_incident()

        tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(BaseException):
                    await t
            source.unsubscribe(queue)
            phone_sockets.discard(ws)

    # --- app shell ---------------------------------------------------------
    @app.get("/{path:path}", include_in_schema=False)
    def shell(path: str):
        index = static_dir / "index.html"
        if not index.is_file():
            return HTMLResponse(NO_SHELL_PAGE)
        if path:
            candidate = (static_dir / path).resolve()
            if candidate.is_file() and candidate.is_relative_to(static_dir):
                headers = {"Cache-Control": "no-cache"} if candidate.name in ("sw.js", "index.html") else None
                return FileResponse(candidate, headers=headers)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app
