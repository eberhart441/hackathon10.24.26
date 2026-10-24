"""Synthetic evacuation for the SIMULATED rooms of the floor plan (demo only).

Fake receivers replay REAL recorded CSI (firmware/tools/data, written by rs-record): empty-room
segments while nobody moves, motion segments while someone does. Their lines go through the same
pipeline as real boards (link activity, room engine, ML line), so the simulated rooms behave the
way real ones would. Every room fed from here is marked "simulated" in the floor plan, and the
app shows the simulated-data badge.

Demo data note: empty-room recordings are replayed only over their longest stretch where the
threshold detector stays quiet on its own (see clean_stretch). On the raw recordings it fires on an
empty room 3-15% of the time per receiver; that false-alarm rate is a known open problem of the live
detector, and is left out here so the simulated floor tells the evacuation story.

Scenario, in seconds since the alarm (before the alarm, occupied rooms have people moving around):
  evacuate   moving until `leave_s`, then gone (quiet)
  trapped    keeps moving the whole time (someone who cannot get out)
  collapsed  moving until `still_s`, then completely still
  empty      nobody, ever
  fails      like evacuate, but the receiver stops reporting at `fail_s` (sensor lost)
"""
from __future__ import annotations

import csv
import random
import threading
import time
from pathlib import Path
from typing import Callable

from roomsense_hub.protocol import CsiRecord, Heartbeat, format_record

PPS = 25  # per fake receiver; the room engine needs at least 20
TRIM_ROWS = 100  # about 3 s of a recording at the relay rate
CALM_S = 25  # everyone still for the first seconds after start, so each receiver learns a quiet level
FAKE_TX_MAC = "02:00:00:00:02:{:02x}"  # locally administered: never a real board

SCENARIO: dict[str, dict] = {
    "RX201": {"kind": "evacuate", "leave_s": 12},
    "RX202": {"kind": "evacuate", "leave_s": 20},
    "RX203": {"kind": "evacuate", "leave_s": 30},
    "RX204": {"kind": "empty"},
    "RX205": {"kind": "fails", "leave_s": 15, "fail_s": 60},
    "RX206": {"kind": "empty"},
    "RX207": {"kind": "trapped"},
    "RX208": {"kind": "evacuate", "leave_s": 25},
    "RX209": {"kind": "collapsed", "still_s": 45},
    "RX210": {"kind": "evacuate", "leave_s": 10},
    "RX211": {"kind": "evacuate", "leave_s": 35},
    "RX212": {"kind": "empty"},
}


def _burst(t: float, on_s: float, off_s: float, phase: float) -> bool:
    """People move in bursts: on for on_s, off for off_s."""
    return (t + phase) % (on_s + off_s) < on_s


def moving(spec: dict, since_alarm: float | None, t: float, phase: float, since_start: float = 1e9) -> bool | None:
    """True = someone moving, False = quiet, None = receiver silent (failed)."""
    kind = spec["kind"]
    if kind == "empty" or (since_alarm is None and since_start < CALM_S):
        return False
    if since_alarm is None:  # before the alarm: occupied rooms have people going about their day
        return _burst(t, 5, 7, phase)
    if kind == "fails" and since_alarm >= spec["fail_s"]:
        return None
    if kind == "trapped":
        return _burst(t, 9, 2, phase)
    if kind == "collapsed":
        return since_alarm < spec["still_s"] and _burst(t, 6, 2, phase)
    return since_alarm < spec["leave_s"]  # evacuate / fails: hurry out, then nobody


def clean_stretch(rows: list[tuple[int, ...]], window: int = 100, step: int = 10) -> list[tuple[int, ...]]:
    """Longest run of rows where the detector's activity measure stays under its motion threshold."""
    import numpy as np
    a = np.asarray(rows, dtype=np.float32)
    live = a.mean(axis=0) > 1
    starts = list(range(0, len(a) - window, step))
    act = np.array([np.median([a[i:i + window, live].std(axis=0).mean()]) for i in starts])
    base = float(np.median(act))
    ok = act < base * 1.8 + 0.4
    best, run_start = (0, 0), None
    for k, good in enumerate(list(ok) + [False]):
        if good and run_start is None:
            run_start = k
        elif not good and run_start is not None:
            if k - run_start > best[1] - best[0]:
                best = (run_start, k)
            run_start = None
    lo, hi = starts[best[0]] if best[1] > best[0] else 0, (starts[best[1] - 1] + window) if best[1] > best[0] else len(a)
    return rows[lo:hi]


def load_pools(data_dir: Path) -> tuple[list[tuple[int, ...]], list[tuple[int, ...]]]:
    """Real recorded amplitude rows: (quiet rows, motion rows), each kept per receiver in recording order."""
    quiet: list[list[tuple[int, ...]]] = []
    motion: list[list[tuple[int, ...]]] = []
    with (data_dir / "manifest.csv").open(newline="", encoding="utf-8") as f:
        sessions = list(csv.DictReader(f))
    for s in sessions:
        pool = quiet if s["label"] == "no_motion_seen" else motion if s["label"] == "motion" else None
        if pool is None or not (data_dir / s["file"]).is_file():
            continue
        per_node: dict[str, list] = {}
        with (data_dir / s["file"]).open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                per_node.setdefault(row["node_id"], []).append(tuple(int(float(row[f"a{i}"])) for i in range(64)))
        # drop the first and last seconds: whoever started and stopped the recording was moving
        pool.extend(rows[TRIM_ROWS:-TRIM_ROWS] for rows in per_node.values() if len(rows) > 200 + 2 * TRIM_ROWS)
    quiet = [clean_stretch(q) for q in quiet]
    quiet = [q for q in quiet if len(q) >= 300] or quiet
    if not quiet or not motion:
        raise ValueError(f"need recorded no_motion_seen and motion sessions in {data_dir} (rs-record)")
    return quiet, motion


class _FakeReceiver:
    def __init__(self, rx: str, tx_mac: str, spec: dict, quiet, motion, rng: random.Random):
        self.rx, self.tx_mac, self.spec = rx, tx_mac, spec
        # one recorded receiver per fake receiver, so its quiet and moving signals belong together
        k = rng.randrange(min(len(quiet), len(motion)))
        self.quiet, self.motion = quiet[k % len(quiet)], motion[k % len(motion)]
        self.pos = {"q": rng.randrange(len(self.quiet)), "m": rng.randrange(len(self.motion))}
        self.phase = rng.uniform(0, 12)
        self.seq = 0

    def next_line(self, since_alarm: float | None, t: float, since_start: float) -> str | None:
        m = moving(self.spec, since_alarm, t, self.phase, since_start)
        if m is None:
            return None
        key, rows = ("m", self.motion) if m else ("q", self.quiet)
        # play the recording forward, then backward, and so on: looping back to the start would
        # put a jump in the signal every pass, which reads as motion
        i, n = self.pos[key], len(rows)
        amps = rows[i % n] if (i // n) % 2 == 0 else rows[n - 1 - i % n]
        self.pos[key] += 1
        self.seq += 1
        return format_record(CsiRecord(self.rx, self.tx_mac, self.seq & 0xFFFFFFFF, int(t * 1e6) & 0xFFFFFFFF,
                                       -60, 11, amps))


def run(feed: Callable[[str], None], alarm_at: Callable[[], float | None], links: list[dict], room_of: dict[str, str],
        data_dir: Path, stop: threading.Event, seed: int = 11) -> None:
    """Feed fake receiver lines in real time until stop is set. alarm_at() is the alarm time or None."""
    quiet, motion = load_pools(data_dir)
    rng = random.Random(seed)
    tx_macs: dict[str, str] = {}
    fakes = []
    for link in links:
        rx = link["rx"]
        if rx not in SCENARIO:
            continue
        mac = tx_macs.setdefault(link["tx"], FAKE_TX_MAC.format(len(tx_macs) + 1))
        fakes.append(_FakeReceiver(rx, mac, SCENARIO[rx], quiet, motion, rng))
    t0 = time.time()
    next_hb = 0.0
    step = 0
    while not stop.is_set():
        now = time.time()
        a = alarm_at()
        since = None if a is None else now - a
        for f in fakes:
            line = f.next_line(since, now, now - t0)
            if line is not None:
                feed(line)
        if now - t0 >= next_hb:
            next_hb += 1.0
            for f in fakes:
                if moving(f.spec, since, now, f.phase, now - t0) is not None:
                    feed(format_record(Heartbeat(f.rx, room_of[f.rx], f.tx_mac, "sim", int((now - t0) * 1000) & 0xFFFFFFFF,
                                                 PPS, 150_000, 0, "HUB")))
        step += 1
        stop.wait(max(0.0, t0 + step / PPS - time.time()))
