import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hub.app import create_app  # noqa: E402
from hub.auth import Auth  # noqa: E402
from hub.mock_source import ScriptedSource  # noqa: E402

FLOORPLAN = ROOT / "hub" / "config" / "floorplan.json"


class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def config_dir(tmp_path):
    (tmp_path / "floorplan.json").write_text(FLOORPLAN.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def make_client(config_dir, *, loopback: bool, auth: Auth | None = None, source=None) -> TestClient:
    app = create_app(
        source or ScriptedSource(),
        config_dir=config_dir,
        static_dir=config_dir / "no-static",
        auth=auth or Auth(config_dir / "secrets.json"),
        is_loopback=lambda _host: loopback,
    )
    return TestClient(app)


@pytest.fixture
def laptop(config_dir):
    with make_client(config_dir, loopback=True) as c:
        token = c.post("/api/local/token").json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        yield c


@pytest.fixture
def phone(config_dir):
    with make_client(config_dir, loopback=False) as c:
        yield c
