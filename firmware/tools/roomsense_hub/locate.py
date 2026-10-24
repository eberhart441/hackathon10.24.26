"""Rough position of motion inside one room, from which radio links are disturbed.

A person who moves near the straight line between a transmitter and a receiver disturbs that
link's signal; one far from it barely does. With several links crossing the room, the place
where the disturbed links overlap (and the quiet links do not pass) is where the motion is.
This is a simplified form of radio tomographic imaging.

What it can and cannot do (keep the UI honest):
  - It estimates a zone, about 1 to 2 m across with four links. It is not meter-precise.
  - It assumes one moving person. Two people far apart produce one blurred estimate between them.
  - It sees motion only. A person who stops moving disappears from the estimate; that never
    means they left.

The layout is a JSON file, distances in feet from the top-left corner of the room:

    {"room": [13, 9.33],
     "links": {"RX1": {"tx": [0, 0], "rx": [13, 4.67]}, ...}}

Each key in "links" is a receiver's node_id; a receiver listens to exactly one transmitter.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

CELL_FT = 0.5          # grid resolution
LINK_WIDTH_FT = 1.2    # how far from a link's line a person still disturbs it noticeably
QUIET_WEIGHT = 0.5     # how strongly a quiet link argues "not here"
PEAK_FRACTION = 0.7    # cells this close to the best one count toward the estimate...
PEAK_RADIUS_FT = 2.5   # ...if they are also this near it, so two separate blobs are not averaged into a gap
SMOOTHING = 0.35       # share of each new estimate in the smoothed position
TRAIL_POINTS = 60      # trail length, one point every TRAIL_EVERY ticks
TRAIL_EVERY = 3
MAX_SCORE = 3.0        # cap so one very noisy link cannot outvote the rest
COVER_WEIGHT = 0.3     # a cell counts as "seen" by a link whose weight there is at least this
MIN_LINKS = 2          # fewer working links than this through the room: motion is reported but not placed


@dataclass(frozen=True)
class Link:
    rx_id: str
    tx: tuple[float, float]
    rx: tuple[float, float]


@dataclass(frozen=True)
class Layout:
    room: tuple[float, float]     # size of the area searched for motion
    links: tuple[Link, ...]
    origin: tuple[float, float] = (0.0, 0.0)  # where that area starts on the floor plan
    # Optional floor-plan wall lines (same feet coordinates as the room, may extend outside it).
    # Drawn on the map only; they do not change the location estimate.
    walls: tuple[tuple[tuple[float, float], ...], ...] = ()

    def to_json(self) -> dict:
        return {"room": list(self.room), "origin": list(self.origin),
                "links": [{"rx_id": l.rx_id, "tx": list(l.tx), "rx": list(l.rx)} for l in self.links],
                "walls": [[list(p) for p in line] for line in self.walls]}


def load_layout(path: Path) -> Layout:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    w, h = (float(v) for v in data["room"])
    walls = tuple(tuple((float(p[0]), float(p[1])) for p in line) for line in data.get("walls", []) if len(line) >= 2)
    links = tuple(Link(rx_id, (float(v["tx"][0]), float(v["tx"][1])), (float(v["rx"][0]), float(v["rx"][1])))
                  for rx_id, v in data["links"].items())
    if w <= 0 or h <= 0 or not links:
        raise ValueError("layout needs a positive room size and at least one link")
    return Layout((w, h), links, walls=walls)


def link_weight(link: Link, x: float, y: float) -> float:
    """How much a person standing at (x, y) disturbs this link, 0 to 1.

    Uses the excess path length (tx -> point -> rx, minus tx -> rx), so the sensitive area is a
    thin ellipse around the line that is widest in the middle, like the real radio zone."""
    direct = math.dist(link.tx, link.rx)
    excess = math.dist(link.tx, (x, y)) + math.dist((x, y), link.rx) - direct
    return math.exp(-(excess / (LINK_WIDTH_FT * 0.5)) ** 2)


def link_score(state: str, activity: float | None, baseline: float | None,
               threshold: float | None) -> float | None:
    """Turn a receiver's activity into a score: 0 = quiet, 1 = at the motion threshold, more = stronger.

    None means the link cannot be judged (warming up, weak, no signal), which is not the same as quiet."""
    if state not in ("motion", "quiet") or activity is None or baseline is None or threshold is None:
        return None
    span = threshold - baseline
    if span <= 0:
        return None
    return max(0.0, min(MAX_SCORE, (activity - baseline) / span))


class Locator:
    """Keeps the smoothed position and trail between ticks."""

    def __init__(self, layout: Layout):
        self.layout = layout
        w, h = layout.room
        ox, oy = layout.origin
        self.cols = max(1, round(w / CELL_FT))
        self.rows = max(1, round(h / CELL_FT))
        self.centres = [(ox + (c + 0.5) * w / self.cols, oy + (r + 0.5) * h / self.rows)
                        for r in range(self.rows) for c in range(self.cols)]
        self.weights = {l.rx_id: [link_weight(l, x, y) for x, y in self.centres] for l in layout.links}
        # Links that actually pass through the room (a receiver parked on its transmitter in the
        # hallway does not); only these count toward "can we place motion in the room".
        self.room_links = {rx for rx, ws in self.weights.items() if max(ws, default=0.0) >= COVER_WEIGHT}
        self.position: tuple[float, float] | None = None
        self.trail: list[tuple[float, float]] = []
        self.ticks = 0

    def update(self, scores: dict[str, float | None], excluded: dict[str, str] | None = None) -> dict:
        """scores: rx_id -> link_score(...), None for a link that cannot be judged.
        excluded: rx_id -> plain-language reason, for links left out because the receiver is off
        (offline, losing packets, glitching...). Returns what the page draws."""
        self.ticks += 1
        excluded = dict(excluded or {})
        for rx_id in self.weights:
            if scores.get(rx_id) is None and rx_id not in excluded:
                excluded[rx_id] = "not reporting"
        room_links = [rx for rx in self.weights if rx in self.room_links]
        healthy = [rx for rx in room_links if scores.get(rx) is not None and rx not in excluded]
        # Where can we still see? A cell no working link passes near is unknown, not empty.
        covered = [any(self.weights[rx][i] >= COVER_WEIGHT for rx in healthy) for i in range(len(self.centres))]

        image = [0.0] * len(self.centres)
        active = []
        for rx_id, weights in self.weights.items():
            s = scores.get(rx_id)
            if s is None or rx_id in excluded:
                continue
            if s >= 1.0:
                active.append(rx_id)
                gain = s
            else:
                gain = -QUIET_WEIGHT * (1.0 - s)
            for i, w in enumerate(weights):
                image[i] += gain * w

        estimate = spread = None
        note = None
        active_in_room = [rx for rx in active if rx in self.room_links]
        # A left-out receiver that still shows motion is reported, never silently dropped: it may be a person.
        suspect = sorted(rx for rx in excluded if (scores.get(rx) or 0.0) >= 1.0)
        if active and len(healthy) < MIN_LINKS:
            # One link alone only says "something moved near this line", not where along it.
            note = (f"Only {len(healthy)} working link{'s' if len(healthy) != 1 else ''} cross the room, "
                    f"so the motion cannot be placed. Disturbed: {', '.join(active)}.")
        elif active and not active_in_room:
            note = f"Motion near {', '.join(active)}, outside the room."
        elif active:
            peak = max(image)
            if peak > 0:
                cut = PEAK_FRACTION * peak
                centre = self.centres[image.index(peak)]
                total = sx = sy = 0.0
                picked = []
                for (x, y), v in zip(self.centres, image):
                    if v >= cut and math.dist((x, y), centre) <= PEAK_RADIUS_FT:
                        total += v
                        sx += v * x
                        sy += v * y
                        picked.append((x, y, v))
                ex, ey = sx / total, sy / total
                spread = max(CELL_FT, math.sqrt(sum(v * ((x - ex) ** 2 + (y - ey) ** 2) for x, y, v in picked) / total))
                # Fewer working links = less certain where along them the person is: widen the zone.
                if len(healthy) < len(room_links):
                    spread *= math.sqrt(len(room_links) / len(healthy))
                if self.position is None:
                    self.position = (ex, ey)
                else:
                    px, py = self.position
                    self.position = (px + SMOOTHING * (ex - px), py + SMOOTHING * (ey - py))
                estimate = self.position
                if self.ticks % TRAIL_EVERY == 0:
                    self.trail.append(estimate)
                    del self.trail[:-TRAIL_POINTS]

        top = max((v for v in image), default=0.0)
        room_off = sorted(rx for rx in excluded if rx in self.room_links)
        if not note and room_off and estimate:
            note = f"Less accurate: {', '.join(room_off)} left out."
        if suspect:
            extra = (f"{', '.join(suspect)} show{'s' if len(suspect) == 1 else ''} motion but "
                     f"{'is' if len(suspect) == 1 else 'are'} unreliable, so it is not placed. Check that area.")
            note = f"{note} {extra}" if note else extra
        return {
            "moving": estimate is not None,
            "motion_seen": bool(active or suspect),
            "x": None if estimate is None else round(estimate[0], 2),
            "y": None if estimate is None else round(estimate[1], 2),
            "spread": None if spread is None else round(spread, 2),
            "last": None if self.position is None else [round(self.position[0], 2), round(self.position[1], 2)],
            "trail": [[round(x, 2), round(y, 2)] for x, y in self.trail],
            "grid": {"cols": self.cols, "rows": self.rows,
                     "cells": [round(max(0.0, v) / top, 2) if top > 0 else 0 for v in image],
                     "covered": covered},
            "scores": {k: (None if v is None else round(v, 2)) for k, v in scores.items()},
            "excluded": excluded,
            "degraded": bool(room_off),
            "note": note,
        }
