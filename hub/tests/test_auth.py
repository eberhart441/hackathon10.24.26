from hub.auth import Auth, token_hash

from .conftest import FakeClock, make_client


def test_pairing_code_is_single_use(tmp_path):
    auth = Auth(tmp_path / "secrets.json", clock=FakeClock())
    code, ttl = auth.new_pairing_code()
    assert len(code) == 6 and code.isdigit() and ttl == 120
    assert auth.pair(code) is not None
    assert auth.pair(code) is None


def test_pairing_code_expires_after_120_s(tmp_path):
    clock = FakeClock()
    auth = Auth(tmp_path / "secrets.json", clock=clock)
    code, _ = auth.new_pairing_code()
    clock.t += 120
    assert auth.pair(code) is None


def test_new_code_invalidates_older(tmp_path):
    auth = Auth(tmp_path / "secrets.json", clock=FakeClock())
    old, _ = auth.new_pairing_code()
    new, _ = auth.new_pairing_code()
    if old != new:
        assert auth.pair(old) is None
    assert auth.pair(new) is not None


def test_phone_token_hash_persists_across_restart(tmp_path):
    auth = Auth(tmp_path / "secrets.json", clock=FakeClock())
    code, _ = auth.new_pairing_code()
    token = auth.pair(code)
    stored = (tmp_path / "secrets.json").read_text()
    assert token not in stored and token_hash(token) in stored
    assert Auth(tmp_path / "secrets.json").kind(token) == "phone"


def test_laptop_token_is_memory_only(tmp_path):
    auth = Auth(tmp_path / "secrets.json")
    token = auth.laptop_token()
    assert auth.kind(token) == "laptop"
    assert Auth(tmp_path / "secrets.json").kind(token) is None
    assert not (tmp_path / "secrets.json").exists()


def test_rate_limit_window(tmp_path):
    clock = FakeClock()
    auth = Auth(tmp_path / "secrets.json", clock=clock)
    assert [auth.rate_limited("a") for _ in range(6)] == [False] * 5 + [True]
    assert auth.rate_limited("b") is False
    clock.t += 60
    assert auth.rate_limited("a") is False


def test_pair_endpoint_flow_and_rate_limit(config_dir):
    auth = Auth(config_dir / "secrets.json")
    with make_client(config_dir, loopback=True, auth=auth) as laptop:
        laptop.headers["Authorization"] = "Bearer " + laptop.post("/api/local/token").json()["token"]
        code = laptop.get("/api/local/pairing-code").json()
        assert set(code) == {"code", "expires_in"}
    with make_client(config_dir, loopback=False, auth=auth) as phone:
        r = phone.post("/api/pair", json={"code": code["code"]})
        assert r.status_code == 200
        token = r.json()["token"]
        assert phone.get("/api/whoami", headers={"Authorization": f"Bearer {token}"}).json() == {"loopback": False}
        assert phone.post("/api/pair", json={"code": code["code"]}).status_code == 401  # used
        statuses = [phone.post("/api/pair", json={"code": "000000"}).status_code for _ in range(5)]
        assert statuses[-1] == 429  # 2 earlier attempts + 4 here exceeds 5/min
        assert 401 in statuses


def test_revoke_phones(config_dir):
    auth = Auth(config_dir / "secrets.json")
    code, _ = auth.new_pairing_code()
    phone_token = auth.pair(code)
    with make_client(config_dir, loopback=True, auth=auth) as laptop:
        laptop.headers["Authorization"] = "Bearer " + laptop.post("/api/local/token").json()["token"]
        assert laptop.post("/api/local/revoke-phones").status_code == 200
        assert laptop.get("/api/whoami").status_code == 200  # laptop token survives
    assert auth.kind(phone_token) is None
    assert Auth(config_dir / "secrets.json").kind(phone_token) is None
