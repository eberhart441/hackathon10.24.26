"""Run the web layer on every configured listener (loopback plus the hotspot address)."""

from __future__ import annotations

import asyncio
import logging
import socket
from pathlib import Path

import uvicorn

from .app import LOOPBACK_HOSTS, create_app
from .settings import Settings
from .source import StateSource

log = logging.getLogger("hub")


def can_bind(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def resolve_listeners(settings: Settings) -> tuple[list[str], bool]:
    """Pick the hosts to serve and whether TLS is on, logging plain-language reasons."""
    tls = True
    for name, p in (("HUB_CERT_FILE", settings.cert_file), ("HUB_KEY_FILE", settings.key_file)):
        if p is None or not p.is_file():
            tls = False
            log.warning("%s is %s, so the hub serves plain HTTP on 127.0.0.1 only. "
                        "The phone cannot connect until the mkcert certificate is in place.",
                        name, f"missing ({p})" if p else "not set")
    hosts = list(settings.bind_hosts) if tls else ["127.0.0.1"]
    usable = []
    for host in hosts:
        if not tls and host not in LOOPBACK_HOSTS:
            continue
        if can_bind(host, settings.port):
            usable.append(host)
        else:
            log.warning("Cannot listen on %s:%d. The address is not on this laptop (is the hotspot on?) "
                        "or the port is in use. Continuing without it.", host, settings.port)
    return usable, tls


def _quiet_connection_resets(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    # Windows' proactor loop logs a traceback whenever a browser drops a socket (tab closed,
    # service worker fetch done, app reconnecting). Nothing failed, so keep the demo log clean.
    if isinstance(context.get("exception"), ConnectionResetError):
        return
    loop.default_exception_handler(context)


async def serve(source: StateSource, settings: Settings | None = None, config_dir: Path | None = None) -> None:
    asyncio.get_running_loop().set_exception_handler(_quiet_connection_resets)
    settings = settings or Settings.load()
    hosts, tls = resolve_listeners(settings)
    if not hosts:
        raise SystemExit("No address to listen on. Check HUB_BIND_HOSTS and HUB_PORT.")
    app = create_app(source, config_dir=config_dir) if config_dir else create_app(source)
    servers = []
    for i, host in enumerate(hosts):
        config = uvicorn.Config(
            app,
            host=host,
            port=settings.port,
            lifespan="on" if i == 0 else "off",  # start the state source once
            ssl_certfile=str(settings.cert_file) if tls else None,
            ssl_keyfile=str(settings.key_file) if tls else None,
            log_level="info",
        )
        servers.append(uvicorn.Server(config))
        scheme = "https" if tls else "http"
        log.info("Listening on %s://%s:%d", scheme, host, settings.port)
    await asyncio.gather(*(s.serve() for s in servers))


def run(source: StateSource, settings: Settings | None = None, config_dir: Path | None = None) -> None:
    """config_dir: folder with floorplan.json (and secrets.json); default hub/config."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(serve(source, settings, config_dir))


