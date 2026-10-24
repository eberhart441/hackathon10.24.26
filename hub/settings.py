"""Hub settings from environment variables, with an optional hub/.env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

HUB_DIR = Path(__file__).resolve().parent


def load_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines; '#' comments and blank lines are skipped."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class Settings:
    bind_hosts: tuple[str, ...]
    port: int
    cert_file: Path | None
    key_file: Path | None

    @classmethod
    def load(cls, env_file: Path = HUB_DIR / ".env") -> "Settings":
        env = {**load_env_file(env_file), **os.environ}  # real env vars win

        def path(name: str) -> Path | None:
            raw = env.get(name, "").strip()
            if not raw:
                return None
            p = Path(raw)
            return p if p.is_absolute() else (HUB_DIR.parent / p)

        hosts = tuple(h.strip() for h in env.get("HUB_BIND_HOSTS", "127.0.0.1,192.168.137.1").split(",") if h.strip())
        return cls(
            bind_hosts=hosts,
            port=int(env.get("HUB_PORT", "8443")),
            cert_file=path("HUB_CERT_FILE"),
            key_file=path("HUB_KEY_FILE"),
        )
