"""Receiver gain correction: a gain change must never look like motion."""
import random

from hypothesis import given, settings
from hypothesis import strategies as st

from beacon_hub.activity import GainReference, live_mean, normalize_gain

packets = st.lists(st.integers(0, 255), min_size=8, max_size=64).filter(lambda a: any(a))


@settings(max_examples=200)
@given(packets, st.floats(0.2, 5.0), st.floats(5.0, 80.0))
def test_a_common_gain_factor_cancels_exactly(amps, gain, reference):
    scaled = [a * gain for a in amps]
    for x, y in zip(normalize_gain(amps, reference), normalize_gain(scaled, reference)):
        assert abs(x - y) < 1e-6


@settings(max_examples=200)
@given(packets, st.floats(5.0, 80.0))
def test_normalized_packet_has_the_reference_mean_and_keeps_zeros(amps, reference):
    out = normalize_gain(amps, reference)
    assert abs(live_mean(out) - reference) < 1e-6
    assert [i for i, a in enumerate(amps) if a == 0] == [i for i, a in enumerate(out) if a == 0]


def test_an_all_zero_packet_stays_zero():
    assert normalize_gain([0] * 8, 20.0) == (0.0,) * 8


def test_the_reference_is_learned_once_and_then_ignores_gain_steps():
    ref = GainReference(packets=5)
    for _ in range(5):
        ref.update([20] * 10)
    assert ref.value == 20
    ref.update([60] * 10)  # gain triples afterwards
    assert ref.value == 20


def test_the_reference_is_not_fooled_by_one_glitch_while_learning():
    ref = GainReference(packets=5)
    for a in (20, 20, 60, 20, 20):
        ref.update([a] * 10)
    assert ref.value == 20


def test_uneven_change_across_subcarriers_survives_normalization():
    rng = random.Random(1)
    base = [20 + rng.randint(0, 1) for _ in range(64)]
    reshaped = [a * (0.5 if i % 2 else 1.5) for i, a in enumerate(base)]  # multipath pattern changed
    a, b = normalize_gain(base, 20), normalize_gain(reshaped, 20)
    assert max(abs(x - y) for x, y in zip(a, b)) > 5
