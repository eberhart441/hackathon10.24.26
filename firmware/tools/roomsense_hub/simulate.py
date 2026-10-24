"""Fake receivers for trying the viewer without boards.

A virtual person walks a loop around the room, pauses, and walks again. Every receiver in the
layout produces protocol-exact CSI and HB lines; a link wobbles more the closer the walker is
to it (same model as locate.link_weight). The first seconds are an empty room so the viewer
learns each link's quiet level.

This checks the plumbing and the page. It says nothing about how well real CSI localizes.
"""
from __future__ import annotations

import math
import random
import threading
import time

from .locate import Layout, link_weight
from .protocol import CsiRecord, Heartbeat, format_record

PPS = 100
EMPTY_S = 6.0       # empty room at start
WALK_S = 24.0       # one lap
STILL_S = 8.0       # standing still after a lap
FAKE_TX = "1a:00:00:00:00:{:02x}"


def walker_at(layout: Layout, t: float) -> tuple[tuple[float, float] | None, bool]:
    """Position of the walker at time t, and whether they are moving. None = nobody in the room."""
    if t < EMPTY_S:
        return None, False
    w, h = layout.room
    # a rounded loop inset from the walls
    phase = (t - EMPTY_S) % (WALK_S + STILL_S)
    lap = min(phase, WALK_S) / WALK_S
    a = 2 * math.pi * lap
    pos = (w / 2 + 0.35 * w * math.cos(a), h / 2 + 0.3 * h * math.sin(2 * a) + 0.1 * h * math.sin(a))
    return pos, phase < WALK_S


def run(layout: Layout, feed, stop: threading.Event, seed: int = 7) -> None:
    """Call feed(line) with simulated serial lines, in real time, until stop is set."""
    rng = random.Random(seed)
    links = layout.links
    base = {l.rx_id: [0 if k in (0, 1, 32) or 27 <= k <= 37 else rng.randint(14, 40) for k in range(64)]
            for l in links}
    phases = {l.rx_id: [rng.uniform(0, 2 * math.pi) for _ in range(64)] for l in links}
    seq = {l.rx_id: 0 for l in links}
    t0 = time.monotonic()
    next_hb = 0.0
    tick = 1.0 / PPS
    k_step = 0
    while not stop.is_set():
        t = time.monotonic() - t0
        pos, moving = walker_at(layout, t)
        for i, link in enumerate(links):
            w = link_weight(link, *pos) if pos and moving else 0.0
            amps = []
            for k, b in enumerate(base[link.rx_id]):
                if b == 0:
                    amps.append(0)
                    continue
                wobble = 0.35 * w * b * math.sin(2 * math.pi * 1.7 * t + phases[link.rx_id][k])
                amps.append(max(0, min(255, round(b + wobble + rng.gauss(0, 0.8)))))
            seq[link.rx_id] += 1
            feed(format_record(CsiRecord(link.rx_id, FAKE_TX.format(i + 1), seq[link.rx_id] & 0xFFFFFFFF,
                                         int(t * 1e6) & 0xFFFFFFFF, -48 - i, 11, tuple(amps))))
        if t >= next_hb:
            next_hb = t + 1.0
            for i, link in enumerate(links):
                feed(format_record(Heartbeat(link.rx_id, "ROOM1", FAKE_TX.format(i + 1), "sim",
                                             int(t * 1000) & 0xFFFFFFFF, PPS, 150_000, 0, "HUB")))
        k_step += 1
        stop.wait(max(0.0, t0 + k_step * tick - time.monotonic()))
