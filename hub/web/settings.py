"""Hub web-layer settings (design: "Hub: settings", Req 4).

Values come from environment variables, optionally loaded from `hub/.env`
(git-ignored). Relative paths resolve against the repository root so commands
work when run from the root or anywhere else.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / "hub" / ".env"

DEFAULTS: dict[str, str] = {
    "HUB_BIND_HOSTS": "127.0.0.1,192.168.137.1",
    "HUB_PORT": "8443",
    "HUB_CERT_FILE": "hub/certs/hub.pem",
    "HUB_KEY_FILE": "hub/certs/hub-key.pem",
    "HUB_SECRETS_FILE": "hub/config/secrets.json",
    "HUB_FLOORPLAN_FILE": "hub/config/floorplan.json",
    "HUB_STATIC_DIR": "hub/static",
    # Test-only (Playwright phone projects): "1" lets requests with header
    # `X-Test-Remote: 1` count as non-loopback. Honored only when every bind
    # host is loopback, and it can only remove privileges.
    "HUB_TEST_FORCE_REMOTE": "0",
}


def _resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


@dataclass(frozen=True)
class Settings:
    bind_hosts: tuple[str, ...]
    port: int
    cert_file: Path
    key_file: Path
    secrets_file: Path
    floorplan_file: Path
    static_dir: Path
    test_force_remote: bool = False

    @classmethod
    def from_mapping(cls, values: Mapping[str, str | None]) -> "Settings":
        """Build settings from a mapping; missing or empty keys use defaults."""

        def get(key: str) -> str:
            raw = values.get(key)
            return raw.strip() if raw and raw.strip() else DEFAULTS[key]

        hosts = tuple(h.strip() for h in get("HUB_BIND_HOSTS").split(",") if h.strip())
        port = int(get("HUB_PORT"))
        if not 1 <= port <= 65535:
            raise ValueError(f"HUB_PORT must be 1-65535, got {port}")
        return cls(
            bind_hosts=hosts,
            port=port,
            cert_file=_resolve(get("HUB_CERT_FILE")),
            key_file=_resolve(get("HUB_KEY_FILE")),
            secrets_file=_resolve(get("HUB_SECRETS_FILE")),
            floorplan_file=_resolve(get("HUB_FLOORPLAN_FILE")),
            static_dir=_resolve(get("HUB_STATIC_DIR")),
            test_force_remote=get("HUB_TEST_FORCE_REMOTE") == "1",
        )

    @classmethod
    def load(cls, env_file: Path | None = ENV_FILE) -> "Settings":
        """Defaults, overridden by `hub/.env`, overridden by process environment."""
        merged: dict[str, str | None] = {}
        if env_file is not None and Path(env_file).is_file():
            merged.update(dotenv_values(env_file))
        merged.update({k: v for k, v in os.environ.items() if k in DEFAULTS})
        return cls.from_mapping(merged)
