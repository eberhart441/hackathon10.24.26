from __future__ import annotations

from pathlib import Path

from hub.web.settings import REPO_ROOT, Settings


def test_defaults_match_design_table() -> None:
    s = Settings.from_mapping({})
    assert s.bind_hosts == ("127.0.0.1", "192.168.137.1")
    assert s.port == 8443
    assert s.cert_file == REPO_ROOT / "hub" / "certs" / "hub.pem"
    assert s.key_file == REPO_ROOT / "hub" / "certs" / "hub-key.pem"
    assert s.secrets_file == REPO_ROOT / "hub" / "config" / "secrets.json"
    assert s.floorplan_file == REPO_ROOT / "hub" / "config" / "floorplan.json"
    assert s.static_dir == REPO_ROOT / "hub" / "static"


def test_env_file_overrides_defaults(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HUB_PORT", raising=False)
    monkeypatch.delenv("HUB_BIND_HOSTS", raising=False)
    env = tmp_path / ".env"
    env.write_text("HUB_PORT=9443\nHUB_BIND_HOSTS= 127.0.0.1 \n", encoding="utf-8")
    s = Settings.load(env)
    assert s.port == 9443
    assert s.bind_hosts == ("127.0.0.1",)


def test_missing_env_file_uses_defaults(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HUB_PORT", raising=False)
    assert Settings.load(tmp_path / "nope.env").port == 8443


def test_gitignore_has_secret_entries() -> None:
    lines = {l.strip() for l in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
    for entry in ("hub/.env", "hub/certs/", "*.pem", "hub/config/secrets.json"):
        assert entry in lines
    assert not any(l.lstrip("/").startswith(".kiro") for l in lines if not l.startswith("#"))
