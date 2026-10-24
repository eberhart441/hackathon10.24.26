"""Example tests for the hub FastAPI app (design: "Hub: routes", Req 2, 3, 5, 6.1, 20)."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from hub.web.app import create_app
from hub.web.settings import Settings

LAPTOP = ("127.0.0.1", 50000)
PHONE = ("192.168.137.5", 50000)


class FakeSource:
    """Minimal StateSource: records commands and emits one room_states message."""

    def __init__(self) -> None:
        self.system_state = "IDLE"
        self.searched: list[str] = []
        self.calls: list[str] = []

    def room_ids(self) -> set[str]:
        return {"R1", "R2"}

    def snapshot(self, now: float) -> list[dict]:
        return [
            {
                "type": "room_states",
                "ts": now,
                "system_state": self.system_state,
                "simulated": True,
                "rooms": [{"room_id": r, "searched": r in self.searched} for r in sorted(self.room_ids())],
                "ranking": sorted(self.room_ids()),
            },
            {"type": "health", "ts": now, "summary": "ok", "nodes": [], "tag_faults": []},
        ]

    def trigger_alarm(self, now: float) -> dict:
        self.calls.append("trigger")
        self.system_state = "ALARM_ACTIVE"
        return {"system_state": "ALARM_ACTIVE", "simulated": True}

    def end_incident(self, now: float) -> dict:
        self.calls.append("end")
        self.system_state = "IDLE"
        self.searched.clear()
        return {"system_state": "IDLE"}

    def mark_searched(self, room_id: str, now: float) -> None:
        self.searched.append(room_id)


@pytest.fixture
def source() -> FakeSource:
    return FakeSource()


@pytest.fixture
def app(source: FakeSource, tmp_settings: Settings):
    tmp_settings.floorplan_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_settings.floorplan_file.write_text('{"floors": []}', encoding="utf-8")
    tmp_settings.static_dir.mkdir(parents=True, exist_ok=True)
    (tmp_settings.static_dir / "index.html").write_text("<!doctype html><p>shell</p>", encoding="utf-8")
    return create_app(source, tmp_settings, ws_auth_timeout_s=0.3)


@pytest.fixture
def laptop(app):
    with TestClient(app, client=LAPTOP) as c:
        yield c


@pytest.fixture
def phone(app, laptop):  # laptop keeps the lifespan running
    return TestClient(app, client=PHONE)


def local_token(laptop: TestClient) -> str:
    r = laptop.post("/api/local/token")
    assert r.status_code == 200
    return r.json()["token"]


def pair_phone(laptop: TestClient, phone: TestClient) -> str:
    code = laptop.get("/api/local/pairing-code", headers=auth(local_token(laptop))).json()["code"]
    r = phone.post("/api/pair", json={"code": code})
    assert r.status_code == 200
    return r.json()["token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


PROTECTED = [
    ("GET", "/api/local/pairing-code"),
    ("POST", "/api/local/revoke-phones"),
    ("GET", "/api/whoami"),
    ("GET", "/api/floorplan"),
    ("POST", "/api/alarm/trigger"),
    ("POST", "/api/incident/end"),
    ("POST", "/api/rooms/R1/searched"),
]
LAPTOP_ONLY = [
    ("GET", "/api/local/pairing-code"),
    ("POST", "/api/local/revoke-phones"),
    ("POST", "/api/alarm/trigger"),
    ("POST", "/api/incident/end"),
    ("POST", "/api/local/token"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_protected_routes_reject_missing_and_bad_tokens(laptop, method, path) -> None:
    for headers in ({}, auth("not-issued"), {"Authorization": "Basic abc"}):
        r = laptop.request(method, path, headers=headers)
        assert r.status_code == 401, (path, headers)
        assert r.headers["cache-control"] == "no-store"
        assert set(r.json()) == {"error"}


@pytest.mark.parametrize(("method", "path"), LAPTOP_ONLY)
def test_laptop_only_routes_403_for_phone_even_with_valid_token(laptop, phone, source, method, path) -> None:
    token = pair_phone(laptop, phone)
    for headers in ({}, auth(token), auth(local_token(laptop))):
        assert phone.request(method, path, headers=headers).status_code == 403
    assert source.calls == [] and source.system_state == "IDLE"


def test_laptop_trigger_and_end_forward_to_source(laptop, source) -> None:
    h = auth(local_token(laptop))
    r = laptop.post("/api/alarm/trigger", headers=h)
    assert r.json() == {"system_state": "ALARM_ACTIVE", "simulated": True}
    assert laptop.post("/api/incident/end", headers=h).json() == {"system_state": "IDLE"}
    assert source.calls == ["trigger", "end"]


def test_pairing_flow_and_single_use_code(laptop, phone, tmp_settings) -> None:
    lh = auth(local_token(laptop))
    code = laptop.get("/api/local/pairing-code", headers=lh).json()
    assert len(code["code"]) == 6 and code["code"].isdigit() and code["expires_in_s"] == 120
    token = phone.post("/api/pair", json={"code": code["code"]}).json()["token"]
    assert phone.get("/api/whoami", headers=auth(token)).json() == {"laptop": False}
    assert laptop.get("/api/whoami", headers=lh).json() == {"laptop": True}
    assert phone.post("/api/pair", json={"code": code["code"]}).status_code == 401  # used
    assert phone.post("/api/pair", content=b"not json").status_code == 401
    assert "phone_token_sha256" in tmp_settings.secrets_file.read_text(encoding="utf-8")


def test_pair_rate_limit_returns_429_before_checking_code(laptop, phone) -> None:
    for _ in range(5):
        assert phone.post("/api/pair", json={"code": "000000x"}).status_code == 401
    code = laptop.get("/api/local/pairing-code", headers=auth(local_token(laptop))).json()["code"]
    assert phone.post("/api/pair", json={"code": code}).status_code == 429


def test_revoke_invalidates_phone_tokens(laptop, phone) -> None:
    token = pair_phone(laptop, phone)
    assert phone.get("/api/whoami", headers=auth(token)).status_code == 200
    assert laptop.post("/api/local/revoke-phones", headers=auth(local_token(laptop))).status_code == 200
    assert phone.get("/api/whoami", headers=auth(token)).status_code == 401


def test_floorplan_read_per_request_and_500_when_missing(laptop, tmp_settings) -> None:
    h = auth(local_token(laptop))
    assert laptop.get("/api/floorplan", headers=h).json() == {"floors": []}
    tmp_settings.floorplan_file.write_text('{"floors": [1]}', encoding="utf-8")
    assert laptop.get("/api/floorplan", headers=h).json() == {"floors": [1]}
    tmp_settings.floorplan_file.unlink()
    r = laptop.get("/api/floorplan", headers=h)
    assert r.status_code == 500 and "could not be read" in r.json()["error"]


def test_mark_searched_unknown_404_known_ok(laptop, phone, source) -> None:
    token = pair_phone(laptop, phone)
    r = phone.post("/api/rooms/R9/searched", headers=auth(token))
    assert r.status_code == 404 and r.json() == {"error": "Unknown room"}
    assert source.searched == []
    assert phone.post("/api/rooms/R1/searched", headers=auth(token)).status_code == 200
    assert source.searched == ["R1"]


def test_mark_searched_broadcasts_immediately(laptop, source) -> None:
    token = local_token(laptop)
    with laptop.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        ws.receive_json(), ws.receive_json()  # initial snapshot
        source.system_state = "ALARM_ACTIVE"
        laptop.post("/api/rooms/R2/searched", headers=auth(token))
        msg = ws.receive_json()
        assert msg["type"] == "room_states"
        assert {"room_id": "R2", "searched": True} in msg["rooms"]


def test_ws_bad_auth_closes_4401(laptop) -> None:
    for first in ('{"type":"auth","token":"nope"}', "garbage", '{"type":"hello"}'):
        with laptop.websocket_connect("/ws") as ws:
            ws.send_text(first)
            with pytest.raises(WebSocketDisconnect) as e:
                ws.receive_text()
            assert e.value.code == 4401


def test_ws_auth_timeout_closes_4401_without_sending_data(laptop) -> None:
    with laptop.websocket_connect("/ws") as ws:
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_text()  # first frame is the close, not data
        assert e.value.code == 4401


def test_phone_ws_ignores_commands_laptop_ws_honors(laptop, phone, source) -> None:
    token = pair_phone(laptop, phone)
    with phone.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        assert ws.receive_json()["type"] == "room_states"
        ws.send_text('{"type":"trigger_alarm"}')
        ws.send_text('{"type":"end_incident"}')
    assert source.calls == []
    with laptop.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": local_token(laptop)}))
        ws.receive_json(), ws.receive_json()
        ws.send_text('{"type":"trigger_alarm"}')
        assert ws.receive_json()["system_state"] == "ALARM_ACTIVE"
    assert source.calls == ["trigger"]


def test_revoke_closes_phone_sockets(laptop, phone) -> None:
    token = pair_phone(laptop, phone)
    with phone.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        ws.receive_json(), ws.receive_json()
        laptop.post("/api/local/revoke-phones", headers=auth(local_token(laptop)))
        with pytest.raises(WebSocketDisconnect) as e:
            while True:
                ws.receive_text()
        assert e.value.code == 4401


def test_static_and_spa_fallback_never_cover_api(laptop, tmp_settings) -> None:
    (tmp_settings.static_dir / "app.js").write_text("console.log(1)", encoding="utf-8")
    assert laptop.get("/app.js").text == "console.log(1)"
    assert "shell" in laptop.get("/").text
    assert "shell" in laptop.get("/some/route").text
    assert laptop.get("/missing.js").status_code == 404
    for path in ("/api/nope", "/api/rooms/R1/searched/extra"):
        r = laptop.get(path)
        assert r.status_code == 404 and r.json() == {"error": "Not found"}
        assert r.headers["cache-control"] == "no-store"
    assert laptop.post("/api/nope").status_code == 404
    assert laptop.get("/ws").status_code == 404


def test_force_remote_flag_strips_laptop_only_on_loopback_binds(source, tmp_settings) -> None:
    forced = replace(tmp_settings, test_force_remote=True)
    with TestClient(create_app(source, forced), client=LAPTOP) as c:
        h = auth(local_token(c))
        assert c.get("/api/whoami", headers=h).json() == {"laptop": True}
        remote = {**h, "X-Test-Remote": "1"}
        assert c.get("/api/whoami", headers=remote).json() == {"laptop": False}
        assert c.post("/api/alarm/trigger", headers=remote).status_code == 403
    # Not honored when a non-loopback bind host is configured.
    mixed = replace(forced, bind_hosts=("127.0.0.1", "192.168.137.1"))
    with TestClient(create_app(source, mixed), client=LAPTOP) as c:
        h = {**auth(local_token(c)), "X-Test-Remote": "1"}
        assert c.get("/api/whoami", headers=h).json() == {"laptop": True}


def test_settings_parse_force_remote_flag() -> None:
    assert Settings.from_mapping({}).test_force_remote is False
    assert Settings.from_mapping({"HUB_TEST_FORCE_REMOTE": "1"}).test_force_remote is True
