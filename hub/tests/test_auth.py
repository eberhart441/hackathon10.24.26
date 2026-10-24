"""Example tests for hub.web.auth primitives (Req 2.1-2.7, 3.4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hub.web.auth import PairingManager, RateLimiter, TokenStore, is_loopback


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


# --- is_loopback -----------------------------------------------------------

@pytest.mark.parametrize(
    "host,expected",
    [
        ("127.0.0.1", True),
        ("127.5.6.7", True),
        ("::1", True),
        ("::ffff:127.0.0.1", True),
        ("192.168.137.1", False),
        ("::ffff:192.168.137.5", False),
        ("10.0.0.2", False),
        ("localhost", False),
        ("", False),
        (None, False),
        ("not-an-ip", False),
    ],
)
def test_is_loopback(host, expected):
    assert is_loopback(host) is expected


# --- PairingManager --------------------------------------------------------

def test_code_is_six_digits_and_reports_ttl():
    pm = PairingManager(FakeClock())
    code, expires_in = pm.new_code()
    assert len(code) == 6 and code.isdigit()
    assert expires_in == 120.0


def test_code_valid_until_120s_then_expires():
    clock = FakeClock()
    pm = PairingManager(clock)
    code, _ = pm.new_code()
    clock.advance(119.9)
    assert pm.redeem(code) is True

    code, _ = pm.new_code()
    clock.advance(120.0)
    assert pm.redeem(code) is False


def test_code_single_use():
    pm = PairingManager(FakeClock())
    code, _ = pm.new_code()
    assert pm.redeem(code) is True
    assert pm.redeem(code) is False


def test_new_code_replaces_prior():
    pm = PairingManager(FakeClock())
    first, _ = pm.new_code()
    second, _ = pm.new_code()
    if first != second:
        assert pm.redeem(first) is False
    assert pm.redeem(second) is True


def test_wrong_code_rejected_and_current_still_works():
    pm = PairingManager(FakeClock())
    code, _ = pm.new_code()
    wrong = f"{(int(code) + 1) % 10**6:06d}"
    assert pm.redeem(wrong) is False
    assert pm.redeem(code) is True


def test_redeem_without_code():
    assert PairingManager(FakeClock()).redeem("000000") is False


# --- RateLimiter -----------------------------------------------------------

def test_sixth_attempt_denied_then_allowed_after_window():
    clock = FakeClock()
    rl = RateLimiter(clock)
    for _ in range(5):
        assert rl.allow("192.168.137.5") is True
        clock.advance(1)
    assert rl.allow("192.168.137.5") is False
    # Other clients are independent.
    assert rl.allow("192.168.137.6") is True
    # First hit was at t=1000; window slides past it at t=1060.
    clock.t = 1060.0
    assert rl.allow("192.168.137.5") is True
    assert rl.allow("192.168.137.5") is False


def test_denied_requests_do_not_extend_lockout():
    clock = FakeClock()
    rl = RateLimiter(clock)
    for _ in range(5):
        assert rl.allow("c")
    for _ in range(59):
        clock.advance(1)
        assert rl.allow("c") is False
    clock.t = 1060.0  # window from the original 5 hits has passed
    assert rl.allow("c") is True


# --- TokenStore ------------------------------------------------------------

def test_phone_token_persists_across_instances(tmp_path: Path):
    path = tmp_path / "config" / "secrets.json"  # parent does not exist yet
    token = TokenStore(path).issue_phone()
    assert path.exists()
    assert TokenStore(path).valid(token) == "phone"


def test_file_holds_only_hashes(tmp_path: Path):
    path = tmp_path / "secrets.json"
    store = TokenStore(path)
    token = store.issue_phone()
    text = path.read_text(encoding="utf-8")
    assert token not in text
    data = json.loads(text)
    assert list(data) == ["phone_token_sha256"]
    assert len(data["phone_token_sha256"]) == 1
    assert len(data["phone_token_sha256"][0]) == 64
    assert list(tmp_path.glob("*.tmp")) == []


def test_local_token_memory_only(tmp_path: Path):
    path = tmp_path / "secrets.json"
    store = TokenStore(path)
    local = store.issue_local()
    assert store.valid(local) == "local"
    assert not path.exists()
    assert TokenStore(path).valid(local) is None


def test_revoke_clears_phones_keeps_local(tmp_path: Path):
    path = tmp_path / "secrets.json"
    store = TokenStore(path)
    phone = store.issue_phone()
    local = store.issue_local()
    store.revoke_phones()
    assert store.valid(phone) is None
    assert store.valid(local) == "local"
    assert TokenStore(path).valid(phone) is None
    assert json.loads(path.read_text(encoding="utf-8")) == {"phone_token_sha256": []}


@pytest.mark.parametrize("bad", [None, "", "not-issued"])
def test_invalid_tokens(tmp_path: Path, bad):
    store = TokenStore(tmp_path / "secrets.json")
    store.issue_phone()
    assert store.valid(bad) is None
