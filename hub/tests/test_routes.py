"""Route example tests filling gaps not covered by test_app.py
(Req 3.2, 3.3, 3.5, 4.5, 5.7, 7.7, 20.1, 20.5, 20.6)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from hub.web.app import create_app
from hub.tests.test_app import (  # noqa: F401  (fixtures re-exported for pytest)
    LAPTOP,
    PHONE,
    FakeSource,
    app,
    auth,
    laptop,
    local_token,
    pair_phone,
    phone,
    source,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _prepare(settings) -> None:
    settings.floorplan_file.parent.mkdir(parents=True, exist_ok=True)
    settings.floorplan_file.write_text('{"floors": []}', encoding="utf-8")
    settings.static_dir.mkdir(parents=True, exist_ok=True)
    (settings.static_dir / "index.html").write_text("<!doctype html><p>shell</p>", encoding="utf-8")


def _ws_auth(ws, token: str) -> None:
    ws.send_text(json.dumps({"type": "auth", "token": token}))
    assert ws.receive_json()["type"] == "room_states"  # nothing sent before auth
    assert ws.receive_json()["type"] == "health"


# --- WS auth-first (Req 3.5) --------------------------------------------------

def test_ws_valid_auth_first_then_snapshot_and_bad_auth_4401(laptop, phone) -> None:
    token = pair_phone(laptop, phone)
    with phone.websocket_connect("/ws") as ws:
        _ws_auth(ws, token)
    with phone.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": "forged"}))
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_text()
        assert e.value.code == 4401


# --- Exempt routes (Req 3.2, 3.3) --------------------------------------------

def test_exempt_routes_work_without_token(laptop, phone) -> None:
    r = phone.get("/")
    assert r.status_code == 200 and "shell" in r.text
    r = laptop.post("/api/local/token")  # no Authorization header
    assert r.status_code == 200 and r.json()["token"]
    code = laptop.get("/api/local/pairing-code", headers=auth(r.json()["token"])).json()["code"]
    r = phone.post("/api/pair", json={"code": code})  # no Authorization header
    assert r.status_code == 200 and r.json()["token"]


# --- Mark searched (Req 5.7, 20.6) -------------------------------------------

def test_mark_searched_broadcast_within_1s_and_404_unknown(source, tmp_settings) -> None:
    _prepare(tmp_settings)
    # Long period: any frame after the initial tick must come from publish_now.
    app = create_app(source, tmp_settings, broadcast_period_s=60.0)
    with TestClient(app, client=LAPTOP) as c:
        token = local_token(c)
        r = c.post("/api/rooms/NOPE/searched", headers=auth(token))
        assert r.status_code == 404 and r.json() == {"error": "Unknown room"}
        with c.websocket_connect("/ws") as ws:
            _ws_auth(ws, token)
            source.system_state = "ALARM_ACTIVE"
            t0 = time.monotonic()
            assert c.post("/api/rooms/R1/searched", headers=auth(token)).status_code == 200
            msg = ws.receive_json()
            assert time.monotonic() - t0 < 1.0
            assert msg["type"] == "room_states"
            assert {"room_id": "R1", "searched": True} in msg["rooms"]
    assert source.searched == ["R1"]


# --- Health cadence (Req 7.7) ------------------------------------------------

def test_health_at_least_1hz_in_idle(source, tmp_settings) -> None:
    _prepare(tmp_settings)
    app = create_app(source, tmp_settings)  # default 1 Hz broadcast
    assert source.system_state == "IDLE"
    with TestClient(app, client=LAPTOP) as c:
        with c.websocket_connect("/ws") as ws:
            _ws_auth(ws, local_token(c))
            stamps: list[float] = []
            while len(stamps) < 3:
                msg = ws.receive_json()
                if msg["type"] == "health":
                    stamps.append(time.monotonic())
                else:
                    assert msg["type"] == "room_states" and msg["rooms"] == []
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(g <= 1.25 for g in gaps), gaps


# --- SPA fallback vs. API 404 (Req 20.1) -------------------------------------

def test_spa_fallback_and_unknown_api_is_json_404(laptop) -> None:
    for path in ("/incident", "/pair/step2"):
        r = laptop.get(path)
        assert r.status_code == 200 and "shell" in r.text
    r = laptop.get("/api/unknown")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"error": "Not found"} and "shell" not in r.text


# --- Repo hygiene (Req 4.5) --------------------------------------------------

def test_gitignore_covers_secrets_and_not_kiro() -> None:
    lines = [
        ln.strip()
        for ln in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    for entry in ("hub/.env", "hub/certs/", "*.pem", "hub/config/secrets.json"):
        assert entry in lines, entry
    assert not any(".kiro" in ln for ln in lines), lines


# --- No occupancy persisted (Req 20.5) ---------------------------------------

def test_incident_writes_no_occupancy_files(laptop, phone, source, tmp_settings) -> None:
    lh = auth(local_token(laptop))
    ptoken = pair_phone(laptop, phone)
    assert laptop.post("/api/alarm/trigger", headers=lh).status_code == 200
    assert phone.post("/api/rooms/R1/searched", headers=auth(ptoken)).status_code == 200
    assert laptop.post("/api/incident/end", headers=lh).status_code == 200
    files = sorted(p.name for p in tmp_settings.secrets_file.parent.rglob("*") if p.is_file())
    assert files == sorted({tmp_settings.floorplan_file.name, tmp_settings.secrets_file.name})
