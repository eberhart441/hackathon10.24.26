"""Property test for hub.web.auth.PairingManager.

Feature: pwa-dashboard, Property 21: Pairing codes work once, only while current and unexpired

**Validates: Requirements 2.1, 2.2, 2.3**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from hub.web.auth import PairingManager

TTL_S = 120.0


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


# Clock advances are multiples of 0.5 s so float arithmetic stays exact and the
# 120 s boundary (expired at exactly 120 s) is hit deliberately.
_advance = st.integers(min_value=0, max_value=300).map(lambda n: ("advance", n / 2))
_ops = st.one_of(
    st.just(("new_code", None)),
    st.just(("redeem_current", None)),
    st.tuples(st.just("redeem_stale"), st.integers(min_value=0, max_value=1000)),
    st.tuples(st.just("redeem_random"), st.integers(min_value=0, max_value=999_999)),
    _advance,
)


@settings(max_examples=200)
@given(st.lists(_ops, min_size=1, max_size=40))
def test_pairing_codes_work_once_only_while_current_and_unexpired(ops) -> None:
    """Feature: pwa-dashboard, Property 21: Pairing codes work once, only while current and unexpired"""
    clock = FakeClock()
    pm = PairingManager(clock, ttl_s=TTL_S)

    # Model state.
    issued: list[str] = []          # every code ever issued, in order
    current: str | None = None      # most recently issued code
    issued_at = 0.0
    current_redeemed = False
    successes: dict[int, int] = {}  # issue index -> number of successful redeems

    for op, arg in ops:
        if op == "new_code":
            code, ttl = pm.new_code()
            assert ttl == TTL_S
            assert isinstance(code, str) and len(code) == 6 and code.isdigit()
            issued.append(code)
            current, issued_at, current_redeemed = code, clock.t, False
            continue
        if op == "advance":
            clock.t += arg
            continue

        if op == "redeem_current":
            if current is None:
                continue
            candidate = current
        elif op == "redeem_stale":
            if len(issued) < 2:
                continue
            candidate = issued[arg % (len(issued) - 1)]  # any earlier code
        else:  # redeem_random; may collide with the current code
            candidate = f"{arg:06d}"

        expected = (
            current is not None
            and candidate == current
            and clock.t - issued_at < TTL_S
            and not current_redeemed
        )
        assert pm.redeem(candidate) is expected, (op, candidate, current, clock.t - issued_at)
        if expected:
            current_redeemed = True
            idx = len(issued) - 1
            successes[idx] = successes.get(idx, 0) + 1

    assert all(n <= 1 for n in successes.values())
