"""Room state engine on live link readings: the parent design's safety rules, with an injected clock."""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from hub import room_engine as re
from hub.room_engine import LinkReading, RoomTrack

HOLD = 30.0


def quiet(node="RX1", hb=0.5, pps=100):
    return LinkReading(node, "quiet", 0.4, hb, pps)


def motion(node="RX1", score=2.0, hb=0.5, pps=100):
    return LinkReading(node, "motion", score, hb, pps)


def dead(node="RX1"):
    return LinkReading(node, "nosignal", None, None, None)


def run(track, steps, t0=0.0, dt=1.0):
    out = []
    t = t0
    for readings in steps:
        out.append(re.update(track, readings, t, HOLD))
        t += dt
    return out, t


reading = st.one_of(
    st.builds(LinkReading, st.just("RX1"), st.sampled_from(["motion", "quiet", "weak", "nosignal", "warming"]),
              st.one_of(st.none(), st.floats(0, 4)), st.one_of(st.none(), st.floats(0, 20)),
              st.one_of(st.none(), st.integers(0, 120))),
)


# Generation speed depends on machine load, not on the property; never fail on it.
@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(st.tuples(st.lists(reading, max_size=3), st.floats(0.1, 20)), min_size=1, max_size=60))
def test_safety_rules_hold_for_any_reading_sequence(steps):
    """Never MOTION -> NO_DETECTION, never NO_DETECTION within the hold of motion evidence,
    always one of four states, and UNKNOWN whenever no link is usable."""
    track = RoomTrack("R1")
    t = 0.0
    prev = None
    for readings, gap in steps:
        e = re.update(track, readings, t, HOLD)
        assert e["state"] in ("MOTION", "POSSIBLE", "UNKNOWN", "NO_DETECTION")
        assert e["label"] != "EMPTY" and 0 <= e["confidence_pct"] <= 100
        if prev == "MOTION":
            assert e["state"] != "NO_DETECTION"
        if e["state"] == "NO_DETECTION" and track.last_evidence is not None:
            assert t - track.last_evidence >= HOLD
        if not any(r.usable() for r in readings):
            assert e["state"] == "UNKNOWN" and e["confidence_pct"] == 0
        if e["state"] == "UNKNOWN":
            assert e["confidence_band"] == "low"
        prev = e["state"]
        t += gap


def test_moving_then_still_is_possible_for_the_hold_then_no_detection():
    track = RoomTrack("R1")
    out, t = run(track, [[quiet()]] * 3 + [[motion()]] * 5)
    assert out[-1]["state"] == "MOTION"
    out, t = run(track, [[quiet()]] * int(HOLD - 2), t0=t)
    assert out[0]["state"] == "MOTION"  # 2-of-3 debounce: one quiet tick does not end motion
    assert {e["state"] for e in out[1:]} == {"POSSIBLE"}  # moved, then still: hold
    out, t = run(track, [[quiet()]] * int(HOLD + 5), t0=t)
    assert out[-1]["state"] == "NO_DETECTION"


def test_motion_needs_two_of_three_ticks():
    track = RoomTrack("R1")
    out, _ = run(track, [[quiet()], [motion()], [quiet()], [quiet()], [motion()], [motion()]])
    assert [e["state"] for e in out][:4] == ["POSSIBLE"] * 4
    assert out[-1]["state"] == "MOTION"


def test_no_detection_needs_a_full_hold_of_quiet_even_at_start():
    """Quiet is not empty: a room that was never watched long enough stays POSSIBLE."""
    track = RoomTrack("R1")
    out, _ = run(track, [[quiet()]] * int(HOLD - 1))
    assert {e["state"] for e in out} == {"POSSIBLE"}


def test_an_offline_link_makes_the_room_unknown_and_stale_with_last_known_state():
    track = RoomTrack("R1")
    _, t = run(track, [[motion()]] * 4)
    out, t = run(track, [[dead()]] * 5, t0=t)
    assert out[-1]["state"] == "UNKNOWN"
    assert out[-1]["stale"] is True and out[-1]["last_known_state"] == "MOTION"
    assert out[-1]["stale_age_s"] == 4


def test_a_returning_link_stays_unknown_for_ten_seconds():
    track = RoomTrack("R1")
    _, t = run(track, [[quiet()]] * 3)
    _, t = run(track, [[dead()]] * 3, t0=t)
    out, _ = run(track, [[motion()]] * 14, t0=t)
    assert [e["state"] for e in out[:10]] == ["UNKNOWN"] * 10
    assert out[-1]["state"] == "MOTION"


def test_a_late_heartbeat_forces_low_confidence_and_blocks_no_detection():
    track = RoomTrack("R1")
    out, _ = run(track, [[quiet(hb=5.0)]] * int(3 * HOLD))
    assert out[-1]["state"] == "POSSIBLE"
    assert out[-1]["confidence_band"] == "low"
    assert out[-1]["link_health"] == "degraded"


def test_one_moving_link_of_several_is_motion():
    track = RoomTrack("R1")
    out, _ = run(track, [[quiet("RX1"), motion("RX2"), quiet("RX3")]] * 3)
    assert out[-1]["state"] == "MOTION"


def test_a_room_whose_links_never_learned_a_baseline_is_uncalibrated_unknown():
    track = RoomTrack("R1")
    out, _ = run(track, [[LinkReading("RX1", "warming", None, 0.5, 100)]] * 5)
    assert out[-1]["state"] == "UNKNOWN" and out[-1]["calibrated"] is False


def test_low_packet_rate_is_tx_dead_and_not_judged():
    track = RoomTrack("R1")
    out, _ = run(track, [[quiet(pps=5)]] * 5)
    assert out[-1]["state"] == "UNKNOWN"
    assert out[-1]["link_health"] == "tx_dead"


def test_motion_last_seen_is_the_last_motion_not_the_last_packet():
    track = RoomTrack("R1")
    _, t = run(track, [[motion()]] * 3)
    out, _ = run(track, [[quiet()]] * 5, t0=t)
    assert out[-1]["last_seen"] == 2.0


# --- presence likelihood and the incident latch ----------------------------------------------------

MOTION_TAIL = re.MOTION_TICKS[1] - 1


def run_incident(track, steps, alarm_at=0.0, t0=0.0, dt=1.0):
    out, t = [], t0
    for readings in steps:
        out.append(re.update(track, readings, t, HOLD, latch_after=alarm_at - re.PRE_ALARM_S))
        t += dt
    return out, t


def test_a_still_room_never_reads_above_ten_percent():
    out, _ = run(RoomTrack("R1"), [[quiet(pps=50), quiet("RX2", pps=48)]] * int(3 * HOLD))
    assert max(e["confidence_pct"] for e in out) <= re.BASELINE_PCT
    assert out[-1]["state"] == "NO_DETECTION" and out[-1]["confidence_pct"] <= re.QUIET_PCT


def test_motion_reads_high_even_at_the_relay_rate_of_50_per_second():
    out, _ = run(RoomTrack("R1"), [[motion(pps=50)]] * 3)
    assert out[-1]["state"] == "MOTION" and out[-1]["confidence_pct"] >= 90
    assert out[-1]["confidence_band"] == "high"


def test_motion_once_during_an_incident_keeps_the_room_flagged_until_the_end():
    track = RoomTrack("R1")
    out, t = run_incident(track, [[quiet()]] * 5 + [[motion()]] * 2)
    assert out[-1]["state"] == "MOTION"
    out, _ = run_incident(track, [[quiet()]] * int(10 * HOLD), t0=t)  # long after the hold
    out = out[MOTION_TAIL:]  # the anti-flicker window keeps MOTION for a tick or two
    assert all(e["state"] == "POSSIBLE" for e in out)
    assert min(e["confidence_pct"] for e in out) >= re.LATCH_FLOOR_PCT
    assert out[-1]["last_seen"] is not None  # "Motion last seen ..." stays on the tile


def test_a_single_motion_tick_is_not_lost():
    """One tick of motion is below the anti-flicker rule for MOTION, but it is still evidence."""
    track = RoomTrack("R1")
    out, t = run_incident(track, [[quiet()]] * 5 + [[motion()]] + [[quiet()]] * 3)
    assert out[-1]["state"] == "POSSIBLE" and out[-1]["confidence_pct"] >= 80
    out, _ = run_incident(track, [[quiet()]] * int(5 * HOLD), t0=t)
    assert out[-1]["state"] == "POSSIBLE"


def test_motion_long_before_the_alarm_does_not_latch():
    track = RoomTrack("R1")
    _, t = run(track, [[motion()]] * 3)  # setting up the boards, long before the alarm
    _, t = run(track, [[quiet()]] * int(re.PRE_ALARM_S + 3 * HOLD), t0=t)
    out, _ = run_incident(track, [[quiet()]] * 5, alarm_at=t, t0=t)
    assert out[-1]["state"] == "NO_DETECTION"


def test_outside_an_incident_the_room_still_settles_after_the_hold():
    track = RoomTrack("R1")
    _, t = run(track, [[motion()]] * 3)
    out, _ = run(track, [[quiet()]] * int(3 * HOLD), t0=t)
    assert out[-1]["state"] == "NO_DETECTION"
