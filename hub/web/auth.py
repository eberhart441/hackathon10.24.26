"""Auth primitives for the hub web layer (Req 2, 3.4, 5.1).

Framework-free: FastAPI dependencies live elsewhere. Every time-dependent
class takes an injected monotonic clock so tests can drive it.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import tempfile
from collections import deque
from pathlib import Path
from typing import Literal, Protocol

__all__ = ["Clock", "is_loopback", "TokenStore", "PairingManager", "RateLimiter"]


class Clock(Protocol):
    def __call__(self) -> float: ...  # monotonic seconds


def is_loopback(host: str | None) -> bool:
    """True only for loopback addresses, including IPv4-mapped IPv6 (::ffff:127.0.0.1)."""
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return addr.is_loopback


def _sha256_hex(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TokenStore:
    """Phone tokens persisted as SHA-256 hashes; local tokens held in memory only."""

    _KEY = "phone_token_sha256"

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._phone_hashes: list[str] = []
        self._local_hashes: list[str] = []
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            return  # unreadable/corrupt file: start with no phone tokens
        hashes = data.get(self._KEY, []) if isinstance(data, dict) else []
        self._phone_hashes = [h for h in hashes if isinstance(h, str)]

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".secrets-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({self._KEY: self._phone_hashes}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def issue_phone(self) -> str:
        token = secrets.token_urlsafe(32)
        self._phone_hashes.append(_sha256_hex(token))
        self._persist()
        return token

    def issue_local(self) -> str:
        token = secrets.token_urlsafe(32)
        self._local_hashes.append(_sha256_hex(token))
        return token

    @staticmethod
    def _matches(candidate: str, hashes: list[str]) -> bool:
        # Check every hash so timing does not depend on which entry matched.
        found = False
        for h in hashes:
            if hmac.compare_digest(candidate, h):
                found = True
        return found

    def valid(self, token: str | None) -> Literal["phone", "local", None]:
        if not token:
            return None
        h = _sha256_hex(token)
        if self._matches(h, self._local_hashes):
            return "local"
        if self._matches(h, self._phone_hashes):
            return "phone"
        return None

    def revoke_phones(self) -> None:
        self._phone_hashes = []
        self._persist()


class PairingManager:
    """At most one live 6-digit code; single use; expires after ttl_s."""

    def __init__(self, clock: Clock, ttl_s: float = 120.0) -> None:
        self._clock = clock
        self._ttl_s = ttl_s
        self._code: str | None = None
        self._expires_at = 0.0

    def new_code(self) -> tuple[str, float]:
        self._code = f"{secrets.randbelow(10**6):06d}"
        self._expires_at = self._clock() + self._ttl_s
        return self._code, self._ttl_s

    def redeem(self, code: str) -> bool:
        current = self._code
        if current is None or not isinstance(code, str):
            return False
        if self._clock() >= self._expires_at:
            self._code = None
            return False
        if not hmac.compare_digest(code.encode("utf-8"), current.encode("utf-8")):
            return False
        self._code = None
        return True


class RateLimiter:
    """Sliding window per client: at most `limit` allowed requests per `window_s`.

    Denied requests are not recorded, so they never extend the lockout.
    """

    def __init__(self, clock: Clock, limit: int = 5, window_s: float = 60.0) -> None:
        self._clock = clock
        self._limit = limit
        self._window_s = window_s
        self._hits: dict[str, deque[float]] = {}

    def allow(self, client: str) -> bool:
        now = self._clock()
        hits = self._hits.setdefault(client, deque())
        while hits and hits[0] <= now - self._window_s:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True
