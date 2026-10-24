"""Listener planning and serving (design: "Hub: listeners", Req 4.1-4.4)."""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass

from hub.web.settings import Settings


@dataclass(frozen=True)
class Listener:
    host: str
    port: int
    tls: bool


def plan_listeners(settings: Settings, cert_ok: bool, local_addrs: set[str]) -> tuple[list[Listener], list[str]]:
    """Returns listeners and plain-language log lines. Never binds 0.0.0.0."""
    if not cert_ok:
        missing = [p for p in (settings.cert_file, settings.key_file) if not p.is_file()] or [
            settings.cert_file,
            settings.key_file,
        ]
        names = " and ".join(str(p) for p in missing)
        return [Listener("127.0.0.1", settings.port, tls=False)], [
            f"Certificate file not found: {names}. Serving plain HTTP on 127.0.0.1 only (laptop browser). "
            "Run mkcert to create it so phones can connect."
        ]
    listeners: list[Listener] = []
    logs: list[str] = []
    for host in settings.bind_hosts:
        if host in ("0.0.0.0", "::"):
            logs.append(f"Refusing to listen on {host}; list specific addresses in HUB_BIND_HOSTS.")
        elif host not in local_addrs:
            logs.append(f"Address {host} is not on this machine (is the hotspot on?). Skipping it.")
        else:
            listeners.append(Listener(host, settings.port, tls=True))
    return listeners, logs


def cert_ok(settings: Settings) -> bool:
    return settings.cert_file.is_file() and settings.key_file.is_file()


def local_addresses() -> set[str]:
    addrs = {"127.0.0.1", "::1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            addrs.add(str(info[4][0]))
    except OSError:
        pass
    return addrs


def url(listener: Listener) -> str:
    host = f"[{listener.host}]" if ":" in listener.host else listener.host
    return f"{'https' if listener.tls else 'http'}://{host}:{listener.port}/"


async def serve(app, listeners: list[Listener], settings: Settings) -> None:
    """Run one uvicorn.Server per listener in one event loop."""
    import uvicorn

    servers = []
    for lst in listeners:
        tls = {"ssl_certfile": str(settings.cert_file), "ssl_keyfile": str(settings.key_file)} if lst.tls else {}
        servers.append(uvicorn.Server(uvicorn.Config(app, host=lst.host, port=lst.port, **tls)))
    await asyncio.gather(*(s.serve() for s in servers))
