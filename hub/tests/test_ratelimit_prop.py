"""Property test for the pairing rate limiter (design Property 22, Req 2.4).

Feature: pwa-dashboard, Property 22: Pairing attempts are rate-limited per client
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from hub.web.auth import RateLimiter

LIMIT = 5
WINDOW_S = 60.0
CLIENTS = ["10.0.0.2", "10.0.0.3", "192.168.1.7", "::ffff:10.0.0.9"]


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# Deltas are multiples of 0.5 s (exact in binary floating point) and include 0,
# so bursts at one instant and attempts landing exactly on the 60 s boundary
# are both exercised.
_delta = st.one_of(
    st.just(0.0),
    st.integers(min_value=0, max_value=30).map(lambda n: n * 0.5),
    st.sampled_from([59.5, 60.0, 60.5, 120.0]),
)
_attempts = st.lists(st.tuples(st.sampled_from(CLIENTS), _delta), min_size=1, max_size=60)


def _in_window(allowed: list[float], now: float) -> int:
    """Allowed attempts in the 60 s window ending at `now`: (now - 60, now]."""
    return sum(1 for t in allowed if now - WINDOW_S < t <= now)


# Feature: pwa-dashboard, Property 22: Pairing attempts are rate-limited per client
@settings(max_examples=200, deadline=None)
@given(_attempts)
def test_pairing_attempts_rate_limited_per_client(attempts: list[tuple[str, float]]) -> None:
    """**Validates: Requirements 2.4**"""
    clock = FakeClock()
    limiter = RateLimiter(clock, limit=LIMIT, window_s=WINDOW_S)

    allowed: dict[str, list[float]] = {c: [] for c in CLIENTS}
    t = 0.0
    for client, delta in attempts:
        t += delta
        clock.now = t
        # Reference model: allowed iff fewer than LIMIT allowed attempts from
        # this same client in the preceding window. Other clients never matter.
        expected = _in_window(allowed[client], t) < LIMIT
        got = limiter.allow(client)
        assert got == expected, (client, t, allowed[client])
        if got:
            allowed[client].append(t)

    # Upper bound: no 60 s window holds more than LIMIT allowed attempts per
    # client. Checking windows ending at each allowed timestamp covers every
    # window, since a window's count only rises when it gains an attempt.
    for client, times in allowed.items():
        for end in times:
            assert _in_window(times, end) <= LIMIT, (client, end, times)


# Feature: pwa-dashboard, Property 22: Pairing attempts are rate-limited per client
@settings(max_examples=100, deadline=None)
@given(_attempts, st.sampled_from(CLIENTS))
def test_clients_are_independent(attempts: list[tuple[str, float]], probe: str) -> None:
    """**Validates: Requirements 2.4**

    The decisions for one client are identical whether or not other clients'
    attempts are interleaved.
    """
    shared_clock, solo_clock = FakeClock(), FakeClock()
    shared = RateLimiter(shared_clock, limit=LIMIT, window_s=WINDOW_S)
    solo = RateLimiter(solo_clock, limit=LIMIT, window_s=WINDOW_S)

    t = 0.0
    for client, delta in attempts:
        t += delta
        shared_clock.now = solo_clock.now = t
        got = shared.allow(client)
        if client == probe:
            assert got == solo.allow(client), (client, t)
