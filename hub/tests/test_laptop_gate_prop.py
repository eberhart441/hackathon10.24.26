"""Property test for the laptop-only gate (design: Property 24, Req 5.1, 5.2).

Feature: pwa-dashboard, Property 24: Laptop-only actions are refused from non-loopback clients
"""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from hub.tests.test_app import LAPTOP, FakeSource, auth
from hub.web.app import create_app
from hub.web.settings import Settings

LAPTOP_ONLY = [
    ("POST", "/api/local/token"),
    ("GET", "/api/local/pairing-code"),
    ("POST", "/api/local/revoke-phones"),
    ("POST", "/api/alarm/trigger"),
    ("POST", "/api/incident/end"),
]


def _is_loopback_addr(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Independent oracle: loopback, including IPv4-mapped ::ffff:127.x."""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped.is_loopback
    return addr.is_loopback


_mapped = st.ip_addresses(v=4).map(lambda a: ipaddress.IPv6Address(f"::ffff:{a}"))
# Plain v4/v6 plus IPv4-mapped v6 so the mapped-loopback filter is exercised.
non_loopback_hosts = (
    st.one_of(st.ip_addresses(v=4), st.ip_addresses(v=6), _mapped)
    .filter(lambda a: not _is_loopback_addr(a))
    .map(str)
)
loopback_hosts = st.one_of(
    st.ip_addresses(network="127.0.0.0/8"),
    st.just(ipaddress.IPv6Address("::1")),
    st.ip_addresses(network="127.0.0.0/8").map(lambda a: ipaddress.IPv6Address(f"::ffff:{a}")),
).map(str)
ports = st.integers(min_value=1, max_value=65535)


@dataclass
class Hub:
    app: FastAPI
    source: FakeSource
    laptop: TestClient
    phone_token: str
    local_token: str


def _make_hub(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Hub]:
    root = tmp_path_factory.mktemp("hub")
    cfg = Settings.from_mapping(
        {
            "HUB_BIND_HOSTS": "127.0.0.1",
            "HUB_CERT_FILE": str(root / "certs" / "hub.pem"),
            "HUB_KEY_FILE": str(root / "certs" / "hub-key.pem"),
            "HUB_SECRETS_FILE": str(root / "config" / "secrets.json"),
            "HUB_FLOORPLAN_FILE": str(root / "config" / "floorplan.json"),
            "HUB_STATIC_DIR": str(root / "static"),
        }
    )
    cfg.floorplan_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.floorplan_file.write_text('{"floors": []}', encoding="utf-8")
    source = FakeSource()
    app = create_app(source, cfg, ws_auth_timeout_s=0.3)
    with TestClient(app, client=LAPTOP) as laptop:  # keeps the lifespan running
        local = laptop.post("/api/local/token").json()["token"]
        code = laptop.get("/api/local/pairing-code", headers=auth(local)).json()["code"]
        phone = TestClient(app, client=("192.168.137.5", 50000))
        phone_token = phone.post("/api/pair", json={"code": code}).json()["token"]
        # Leave a live pairing code so "unchanged" is a meaningful check.
        laptop.get("/api/local/pairing-code", headers=auth(local))
        yield Hub(app, source, laptop, phone_token, local)


@pytest.fixture(scope="module")
def hub(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Hub]:
    # One app reused across examples: every refused request must leave it
    # untouched, so the before/after comparison below is the property itself.
    yield from _make_hub(tmp_path_factory)


@pytest.fixture(scope="module")
def control_hub(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Hub]:
    yield from _make_hub(tmp_path_factory)


def _pairing_state(app: FastAPI) -> tuple:
    p = app.state.pairing
    return (p._code, p._expires_at)


def _token_choice(hub: Hub, choice: str) -> dict:
    return {
        "none": {},
        "phone": auth(hub.phone_token),
        "local": auth(hub.local_token),
        "bogus": auth("not-issued"),
    }[choice]


TOKENS = st.sampled_from(["none", "phone", "local", "bogus"])


# Feature: pwa-dashboard, Property 24: Laptop-only actions are refused from non-loopback clients
@settings(max_examples=150, deadline=None)
@given(host=non_loopback_hosts, port=ports, endpoint=st.sampled_from(LAPTOP_ONLY), token=TOKENS)
def test_laptop_only_http_refused_from_non_loopback(hub: Hub, host, port, endpoint, token) -> None:
    """**Validates: Requirements 5.1, 5.2**"""
    before = (hub.source.system_state, list(hub.source.calls), _pairing_state(hub.app))
    method, path = endpoint
    r = TestClient(hub.app, client=(host, port)).request(method, path, headers=_token_choice(hub, token))
    assert r.status_code == 403, (host, endpoint, token, r.status_code)
    assert (hub.source.system_state, hub.source.calls, _pairing_state(hub.app)) == before
    assert hub.app.state.tokens.valid(hub.phone_token) == "phone"  # not revoked


# Fewer examples: each WebSocket session spins up a full ASGI round trip with
# auth, an initial snapshot, and a close, which is ~10x slower than one HTTP
# request; 30 examples still cover v4, v6, and mapped hosts with both tokens.
# Feature: pwa-dashboard, Property 24: Laptop-only actions are refused from non-loopback clients
@settings(max_examples=30, deadline=None)
@given(host=non_loopback_hosts, port=ports, token=st.sampled_from(["phone", "local"]))
def test_ws_commands_ignored_from_non_loopback(hub: Hub, host, port, token) -> None:
    """**Validates: Requirements 5.1, 5.2**"""
    before = (hub.source.system_state, list(hub.source.calls))
    t = hub.phone_token if token == "phone" else hub.local_token
    with TestClient(hub.app, client=(host, port)).websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": t}))
        assert ws.receive_json()["type"] == "room_states"  # authenticated
        ws.send_text('{"type":"trigger_alarm"}')
        ws.send_text('{"type":"end_incident"}')
    assert (hub.source.system_state, hub.source.calls) == before


# Positive control: loopback peers with a valid local token are allowed.
# Feature: pwa-dashboard, Property 24: Laptop-only actions are refused from non-loopback clients
@settings(max_examples=50, deadline=None)
@given(host=loopback_hosts, port=ports)
def test_loopback_with_local_token_allowed(control_hub: Hub, host, port) -> None:
    """**Validates: Requirements 5.1, 5.2**"""
    c = TestClient(control_hub.app, client=(host, port))
    h = auth(control_hub.local_token)
    assert c.post("/api/local/token").status_code == 200
    assert c.get("/api/local/pairing-code", headers=h).status_code == 200
    n = len(control_hub.source.calls)
    assert c.post("/api/alarm/trigger", headers=h).status_code == 200
    assert c.post("/api/incident/end", headers=h).status_code == 200
    assert control_hub.source.calls[n:] == ["trigger", "end"]
