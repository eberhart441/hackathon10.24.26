"""Property test for hub.web.auth.TokenStore.

Feature: pwa-dashboard, Property 23: Phone tokens survive restart and die on revoke

**Validates: Requirements 2.5, 2.6, 2.7**
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from hub.web.auth import TokenStore

_ops = st.one_of(
    st.just(("issue_phone", None)),
    st.just(("issue_local", None)),
    st.just(("restart", None)),
    st.just(("revoke_phones", None)),
    st.tuples(st.just("check_issued"), st.integers(min_value=0, max_value=1000)),
    st.tuples(st.just("check_random"), st.text(max_size=48)),
)


@settings(max_examples=200, deadline=None)
@given(st.lists(_ops, min_size=1, max_size=40))
def test_phone_tokens_survive_restart_and_die_on_revoke(ops) -> None:
    """Feature: pwa-dashboard, Property 23: Phone tokens survive restart and die on revoke"""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "secrets.json"
        store = TokenStore(path)

        # Model: token -> expected valid() result under the current store.
        expected: dict[str, str | None] = {}
        issued: list[str] = []  # every token ever issued, in order

        def check(token: str) -> None:
            assert store.valid(token) == expected.get(token), (token, expected.get(token))

        for op, arg in ops:
            if op == "issue_phone":
                t = store.issue_phone()
                issued.append(t)
                expected[t] = "phone"
            elif op == "issue_local":
                t = store.issue_local()
                issued.append(t)
                expected[t] = "local"
            elif op == "restart":
                store = TokenStore(path)
                # Local tokens are in-memory only (Req 2.7); phone tokens persist (Req 2.5).
                for t, kind in expected.items():
                    if kind == "local":
                        expected[t] = None
            elif op == "revoke_phones":
                store.revoke_phones()
                # Revoke kills every phone token (Req 2.6); local tokens unaffected.
                for t, kind in expected.items():
                    if kind == "phone":
                        expected[t] = None
            elif op == "check_issued":
                if issued:
                    check(issued[arg % len(issued)])
            else:  # check_random
                if arg not in expected:
                    assert store.valid(arg) is None, arg

            # The secrets file never contains a raw token (Req 2.5).
            if path.exists():
                content = path.read_text(encoding="utf-8")
                for t in issued:
                    assert t not in content

        # Final sweep: current store and a freshly reloaded store agree with the model.
        for t in issued:
            check(t)
        reloaded = TokenStore(path)
        for t in issued:
            want = "phone" if expected[t] == "phone" else None
            assert reloaded.valid(t) == want, (t, want)
