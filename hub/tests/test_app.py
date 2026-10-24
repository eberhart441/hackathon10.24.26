import json
import re
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

from hub.auth import Auth

from .conftest import make_client

PROTECTED = [
    ("get", "/api/whoami"),
    ("get", "/api/floorplan"),
    ("get", "/api/local/pairing-code"),
    ("post", "/api/local/revoke-phones"),
    ("post", "/api/alarm/trigger"),
    ("post", "/api/incident/end"),
    ("post", "/api/rooms/R1/searched"),
]
LAPTOP_ONLY = [
    ("get", "/api/local/pairing-code"),
    ("post", "/api/local/revoke-phones"),
    ("post", "/api/alarm/trigger"),
    ("post", "/api/incident/end"),
    ("post", "/api/local/token"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_protected_routes_need_token(config_dir, method, path):
    with make_client(config_dir, loopback=True) as c:
        for headers in ({}, {"Authorization": "Bearer not-a-token"}):
            r = getattr(c, method)(path, headers=headers)
            assert r.status_code == 401
            assert r.headers["cache-control"] == "no-store"
            assert "rooms" not in r.text and "R1" not in r.text.replace(path, "")


@pytest.mark.parametrize("method,path", LAPTOP_ONLY)
def test_laptop_only_routes_reject_phone_even_with_token(config_dir, method, path):
    auth = Auth(config_dir / "secrets.json")
    code, _ = auth.new_pairing_code()
    token = auth.pair(code)
    with make_client(config_dir, loopback=False, auth=auth) as phone:
        r = getattr(phone, method)(path, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403
        assert phone.app.state.source.frame()["room_states"]["system_state"] == "IDLE"


def test_floorplan_read_at_request_time(laptop, config_dir):
    assert laptop.get("/api/floorplan").json()["floors"][0]["id"] == "F1"
    data = json.loads((config_dir / "floorplan.json").read_text())
    data["floors"][0]["name"] = "Edited"
    (config_dir / "floorplan.json").write_text(json.dumps(data))
    assert laptop.get("/api/floorplan").json()["floors"][0]["name"] == "Edited"


def test_alarm_trigger_idempotent_and_end(laptop):
    assert laptop.post("/api/alarm/trigger").json() == {"system_state": "ALARM_ACTIVE", "simulated": True}
    assert laptop.post("/api/alarm/trigger").status_code == 200
    rs = laptop.app.state.source.latest()["room_states"]
    assert rs["system_state"] == "ALARM_ACTIVE" and len(rs["rooms"]) == 6
    assert laptop.post("/api/incident/end").json()["system_state"] == "IDLE"
    assert laptop.app.state.source.latest()["room_states"]["rooms"] == []


def test_searched_unknown_room_404(laptop):
    assert laptop.post("/api/rooms/R99/searched").status_code == 404
    assert laptop.app.state.source.latest()["room_states"]["system_state"] == "IDLE"


def test_searched_moves_room_last(laptop):
    laptop.post("/api/alarm/trigger")
    first = laptop.app.state.source.latest()["room_states"]["ranking"][0]
    assert laptop.post(f"/api/rooms/{first}/searched").status_code == 200
    rs = laptop.app.state.source.latest()["room_states"]
    assert rs["ranking"][-1] == first
    assert next(r for r in rs["rooms"] if r["room_id"] == first)["searched"] is True


def test_idle_room_states_have_no_rooms(laptop):
    rs = laptop.app.state.source.latest()["room_states"]
    assert rs["system_state"] == "IDLE" and rs["rooms"] == [] and rs["ranking"] == []
    assert laptop.app.state.source.latest()["recording"]["stored_samples"] == 0


def test_ws_rejects_bad_auth(laptop):
    with laptop.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": "nope"}))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 4401


def test_ws_streams_latest_after_auth(laptop):
    token = laptop.headers["Authorization"].split()[1]
    with laptop.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        types = {ws.receive_json()["type"] for _ in range(4)}
        assert types == {"room_states", "health", "crew", "recording"}
        ws.send_text(json.dumps({"type": "trigger_alarm"}))  # loopback client: allowed
        for _ in range(20):
            msg = ws.receive_json()
            if msg["type"] == "room_states" and msg["system_state"] == "ALARM_ACTIVE":
                break
        else:
            pytest.fail("alarm never broadcast")


def test_ws_phone_cannot_trigger_alarm(config_dir):
    auth = Auth(config_dir / "secrets.json")
    code, _ = auth.new_pairing_code()
    token = auth.pair(code)
    with make_client(config_dir, loopback=False, auth=auth) as phone:
        with phone.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": token}))
            ws.receive_json()
            ws.send_text(json.dumps({"type": "trigger_alarm"}))
            ws.send_text(json.dumps({"type": "end_incident"}))
            ws.receive_json()
        assert phone.app.state.source.latest()["room_states"]["system_state"] == "IDLE"


def test_shell_without_build_shows_message(laptop):
    r = laptop.get("/")
    assert r.status_code == 200 and "does not replace a full search" in r.text


def test_shell_spa_fallback_and_sw_headers(config_dir, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>shell</html>")
    (static / "sw.js").write_text("// sw")
    from fastapi.testclient import TestClient

    from hub.app import create_app
    from hub.mock_source import ScriptedSource

    with TestClient(create_app(ScriptedSource(), config_dir=config_dir, static_dir=static)) as c:
        assert c.get("/some/deep/route").text == "<html>shell</html>"
        sw = c.get("/sw.js")
        assert sw.text == "// sw" and sw.headers["cache-control"] == "no-cache"
        assert c.get("/api/nope").status_code == 404
        assert c.get("/../../secrets.json").text == "<html>shell</html>"


def test_hub_writes_only_secrets_json():
    """Static scan: the only disk writes in the hub package are the secrets file in auth.py."""
    hub_dir = Path(__file__).resolve().parents[1]
    write_calls = re.compile(r"open\([^)]*['\"][wax]b?\+?['\"]|\.write_text\(|\.write_bytes\(|\.replace\(self\._path")
    offenders = {}
    for py in hub_dir.glob("*.py"):
        hits = write_calls.findall(py.read_text(encoding="utf-8"))
        if hits:
            offenders[py.name] = hits
    assert set(offenders) <= {"auth.py"}, offenders
