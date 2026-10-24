"""Pairing codes and bearer tokens.

Phone tokens are persisted only as SHA-256 hashes in secrets.json so a hub
restart does not unpair the phone. The laptop token lives in memory only.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Callable

CODE_TTL_S = 120
PAIR_LIMIT = 5
PAIR_WINDOW_S = 60

Clock = Callable[[], float]


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Auth:
    def __init__(self, secrets_path: Path, clock: Clock = time.monotonic):
        self._path = Path(secrets_path)
        self._clock = clock
        self._code: str | None = None
        self._code_expires = 0.0
        self._laptop_hashes: set[str] = set()
        self._phone_hashes: set[str] = self._load()
        self._pair_attempts: dict[str, deque[float]] = defaultdict(deque)

    # --- persistence -------------------------------------------------------
    def _load(self) -> set[str]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return set(data.get("phone_token_hashes", []))
        except (FileNotFoundError, ValueError):
            return set()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"phone_token_hashes": sorted(self._phone_hashes)}, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    # --- pairing codes -----------------------------------------------------
    def new_pairing_code(self) -> tuple[str, int]:
        """Issue a fresh 6-digit code; any earlier unused code stops working."""
        self._code = f"{secrets.randbelow(1_000_000):06d}"
        self._code_expires = self._clock() + CODE_TTL_S
        return self._code, CODE_TTL_S

    def code_remaining(self) -> int:
        if self._code is None:
            return 0
        return max(0, int(round(self._code_expires - self._clock())))

    def rate_limited(self, client: str) -> bool:
        """Record a pair attempt; True if this attempt exceeds 5 per 60 s."""
        now = self._clock()
        q = self._pair_attempts[client]
        while q and now - q[0] >= PAIR_WINDOW_S:
            q.popleft()
        q.append(now)
        return len(q) > PAIR_LIMIT

    def pair(self, code: str) -> str | None:
        """Exchange the current code for a persisted phone token, or None."""
        current = self._code
        if current is None or self._clock() >= self._code_expires:
            return None
        if not hmac.compare_digest(str(code).encode(), current.encode()):
            return None
        self._code = None  # single use
        token = secrets.token_urlsafe(32)
        self._phone_hashes.add(token_hash(token))
        self._save()
        return token

    # --- tokens ------------------------------------------------------------
    def laptop_token(self) -> str:
        token = secrets.token_urlsafe(32)
        self._laptop_hashes.add(token_hash(token))
        return token

    def kind(self, token: str | None) -> str | None:
        """'laptop', 'phone', or None for an unknown token (constant-time per hash)."""
        if not token:
            return None
        h = token_hash(token).encode()
        found = None
        for kind, hashes in (("laptop", self._laptop_hashes), ("phone", self._phone_hashes)):
            for known in hashes:
                if hmac.compare_digest(h, known.encode()):
                    found = kind
        return found

    def valid(self, token: str | None) -> bool:
        return self.kind(token) is not None

    def revoke_phones(self) -> None:
        self._phone_hashes.clear()
        self._save()
