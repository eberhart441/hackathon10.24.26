"""Property test: every protected /api route rejects unknown tokens (design Property 20).

Feature: pwa-dashboard, Property 20: Every protected route rejects unknown tokens
**Validates: Requirements 3.1, 3.5**
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from hub.tests.test_app import LAPTOP, LAPTOP_ONLY, PHONE, PROTECTED, FakeSource, auth
from hub.web.app import create_app
from hub.web.settings import Settings

EXEMPT = {("POST", "/api/pair"), ("POST", "/api/local/token")}
CATCH_ALL = "/api/{rest:path}"
DATA_KEYS = {"rooms", "tags", "nodes", "floors", "indicator", "ranking", "recording"}


def _build(tmp: Path):
    s = Settings.from_mapping(
        {
            "HUB_BIND_HOSTS": "127.0.0.1",
            "HUB_CERT_FILE": str(tmp / "certs" / "hub.pem"),
            "HUB_KEY_FILE": str(tmp / "certs" / "hub-key.pem"),
            "HUB_SECRETS_FILE": str(tmp / "config" / "secrets.json"),
            "HUB_FLOORPLAN_FILE": str(tmp / "config" / "floorplan.json"),
            "HUB_STATIC_DIR": str(tmp / "static"),
        }
    )
    s.floorplan_file.parent.mkdir(parents=True, exist_ok=True)
    s.floorplan_file.write_text('{"floors": [{"id": "F1"}]}', encoding="utf-8")
    s.static_dir.mkdir(parents=True, exist_ok=True)
    (s.static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    return create_app(FakeSource(), s, ws_auth_timeout_s=0.3)


def protected_routes(app) -> list[tuple[str, str]]:
    """Every (method, concrete path) under /api/ except the exempt routes and catch-all."""
    found: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
            continue
        if route.path == CATCH_ALL:
            continue
        for method in route.methods:
            if method == "HEAD" or (method, route.path) in EXEMPT:
                continue
            found.add((method, re.sub(r"\{[^}]+\}", "R1", route.path)))
    return sorted(found)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    app = _build(tmp_path_factory.mktemp("routes_prop"))
    with TestClient(app, client=LAPTOP) as laptop:
        phone = TestClient(app, client=PHONE)
        local = laptop.post("/api/local/token").json()["token"]
        code = laptop.get("/api/local/pairing-code", headers=auth(local)).json()["code"]
        revoked = phone.post("/api/pair", json={"code": code}).json()["token"]
        assert phone.get("/api/whoami", headers=auth(revoked)).status_code == 200
        assert laptop.post("/api/local/revoke-phones", headers=auth(local)).status_code == 200
        yield {
            "app": app,
            "laptop": laptop,
            "phone": phone,
            "local": local,
            "revoked": revoked,
            "routes": protected_routes(app),
        }


def test_route_enumeration_covers_known_protected_routes(env) -> None:
    routes = set(env["routes"])
    assert len(routes) >= len(PROTECTED)
    assert set(PROTECTED) <= routes, set(PROTECTED) - routes


def test_valid_local_token_from_loopback_is_not_rejected(env) -> None:
    for method, path in env["routes"]:
        r = env["laptop"].request(method, path, headers=auth(env["local"]))
        assert r.status_code not in (401, 403), (method, path, r.status_code)


# Header values httpx can send: printable ASCII, no CR/LF.
_text = st.text(alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E), max_size=40)


def _headers(local: str, revoked: str):
    value = st.one_of(
        st.just(""),
        _text,
        _text.map(lambda t: f"Bearer {t}"),
        _text.map(lambda t: f"bearer {t}"),
        st.sampled_from(["Basic", "Token", "Digest", "Bearer"]).map(lambda s: f"{s}  "),
        st.sampled_from(["Basic", "Token", "Digest", "JWT"]).map(lambda s: f"{s} {local}"),
        st.just(local),  # bare token, no scheme
        st.just(f"Bearer {revoked}"),
        st.just(f"bearer {revoked}"),
    )
    return st.one_of(st.none(), value).map(
        lambda v: {} if v is None else {"Authorization": v}
    )


@settings(max_examples=150, deadline=None)
@given(data=st.data())
def test_every_protected_route_rejects_unknown_tokens(env, data) -> None:
    """Feature: pwa-dashboard, Property 20: Every protected route rejects unknown tokens"""
    headers = data.draw(_headers(env["local"], env["revoked"]), label="headers")
    laptop_only = set(LAPTOP_ONLY)
    for method, path in env["routes"]:
        # Loopback: always 401.
        r = env["laptop"].request(method, path, headers=headers)
        assert r.status_code == 401, (method, path, headers, r.status_code)
        body = r.json()
        assert set(body) == {"error"} and not DATA_KEYS & set(body)
        assert r.headers["cache-control"] == "no-store"
        # Non-loopback: 401, or 403 on laptop-only endpoints.
        r = env["phone"].request(method, path, headers=headers)
        allowed = {401, 403} if (method, path) in laptop_only else {401}
        assert r.status_code in allowed, (method, path, headers, r.status_code)
        if (method, path) in laptop_only:
            assert r.status_code == 403
        assert set(r.json()) == {"error"}
