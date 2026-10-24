"""Shared pytest fixtures for hub tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hub.web.settings import Settings  # noqa: E402


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    """Settings pointing config, certs, and static at a temp dir (no hub/.env)."""
    return Settings.from_mapping(
        {
            "HUB_BIND_HOSTS": "127.0.0.1",
            "HUB_CERT_FILE": str(tmp_path / "certs" / "hub.pem"),
            "HUB_KEY_FILE": str(tmp_path / "certs" / "hub-key.pem"),
            "HUB_SECRETS_FILE": str(tmp_path / "config" / "secrets.json"),
            "HUB_FLOORPLAN_FILE": str(tmp_path / "config" / "floorplan.json"),
            "HUB_STATIC_DIR": str(tmp_path / "static"),
        }
    )
