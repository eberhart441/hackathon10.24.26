"""ML classification shown under each room's normal text. It never changes the room state.

Keeps the last WINDOW_PACKETS amplitude rows per receiver, prepares them exactly as ml/train.py did
(5-packet median filter, scaled to 0..1), and runs the baseline model from ml/model/baseline.json
(pure numpy). A room's result is its most motion-like receiver.

Privacy: amplitudes stay in RAM in this process; only {label, motion_pct} per room leaves it.
"""
from __future__ import annotations

import json
import threading
from collections import deque
from pathlib import Path

import numpy as np

from ml.baseline import Baseline, window_features
from roomsense_hub.protocol import CsiRecord, parse_line

WINDOW_PACKETS = 150  # must match ml/features.py
MEDIAN_KERNEL = 5     # must match ml/features.py
MOTION_LABEL = "motion"


class MLClassifier:
    def __init__(self, model_path: Path):
        self.model = Baseline.load(model_path)
        names = json.loads(Path(model_path).read_text(encoding="utf-8"))["classes"]
        if MOTION_LABEL not in names:
            raise ValueError(f"{model_path} has no '{MOTION_LABEL}' class")
        self.motion_col = names.index(MOTION_LABEL)
        self.lock = threading.Lock()
        self.buffers: dict[str, deque] = {}

    def feed_line(self, line: str) -> None:
        """Called for every serial line (any thread); keeps only CSI amplitudes."""
        if not line.startswith("CSI,"):
            return
        rec = parse_line(line)
        if isinstance(rec, CsiRecord):
            with self.lock:
                self.buffers.setdefault(rec.node_id, deque(maxlen=WINDOW_PACKETS)).append(rec.amplitudes)

    def motion_probability(self, node_id: str) -> float | None:
        with self.lock:
            buf = self.buffers.get(node_id)
            if buf is None or len(buf) < WINDOW_PACKETS:
                return None
            rows = np.array(buf, dtype=np.float32)
        window = _median_filter(rows) / 255.0
        return float(self.model.predict_proba(window_features(window[None]))[0, self.motion_col])

    def room(self, receivers: list[str]) -> dict | None:
        """{"label": "motion" | "no motion", "motion_pct": 0..100}, or None until a receiver has a full window."""
        probs = [p for p in (self.motion_probability(rx) for rx in receivers) if p is not None]
        if not probs:
            return None
        p = max(probs)
        return {"label": "motion" if p >= 0.5 else "no motion", "motion_pct": int(round(100 * p))}


def _median_filter(rows: np.ndarray, kernel: int = MEDIAN_KERNEL) -> np.ndarray:
    """Per-subcarrier median over `kernel` packets, shrinking at the edges like ml/features.py."""
    half = kernel // 2
    out = np.empty_like(rows)
    for t in range(len(rows)):
        out[t] = np.median(rows[max(0, t - half):t + half + 1], axis=0)
    return out
