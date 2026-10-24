"""Packet-loss accounting from counter gaps."""
from hypothesis import given
from hypothesis import strategies as st

from roomsense_hub import SequenceTracker


def feed(values, **kw):
    tracker = SequenceTracker(**kw)
    events = [tracker.update(v) for v in values]
    return tracker, events


def test_a_clean_stream_has_no_loss():
    tracker, _ = feed(range(100, 200))
    assert (tracker.received, tracker.lost, tracker.loss_rate) == (100, 0, 0.0)


def test_gaps_count_the_missing_packets():
    tracker, events = feed([1, 2, 3, 7, 8, 12])
    assert tracker.lost == 3 + 3  # 4,5,6 and 9,10,11
    assert [e.lost for e in events if e.kind == "gap"] == [3, 3]


def test_a_backwards_counter_is_a_restart_not_loss():
    tracker, events = feed([1000, 1001, 1002, 0, 1, 2])
    assert tracker.lost == 0
    assert tracker.restarts == 1
    assert events[3].kind == "restart"


def test_duplicates_are_ignored():
    tracker, _ = feed([5, 6, 6, 7])
    assert (tracker.received, tracker.duplicates, tracker.lost) == (3, 1, 0)


def test_counter_wraparound_is_continuous():
    tracker, _ = feed([4294967294, 4294967295, 0, 1])
    assert (tracker.lost, tracker.restarts) == (0, 0)


def test_a_huge_forward_jump_is_a_discontinuity_not_loss():
    tracker, events = feed([1, 2, 5_000_000], max_gap=100_000)
    assert tracker.lost == 0
    assert events[-1].kind == "discontinuity"


@given(st.lists(st.integers(1, 5), min_size=1, max_size=200))
def test_lost_equals_the_missing_counter_values(steps):
    # Build a strictly increasing stream from the steps; loss must equal the skipped values.
    values, current = [], 0
    for step in steps:
        current += step
        values.append(current)
    tracker, _ = feed(values)
    expected_lost = sum(step - 1 for step in steps[1:])
    assert tracker.lost == expected_lost
    assert tracker.received == len(values)
    assert 0.0 <= tracker.loss_rate <= 1.0
