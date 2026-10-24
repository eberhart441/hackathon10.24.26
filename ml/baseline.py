"""Simple baseline: a few "how much does the signal wobble" numbers per window + logistic regression.

Pure numpy (no TensorFlow, no scikit-learn), small enough to train on a handful of sessions.
The features describe the shape of the signal over a window and deliberately leave out the packet
rate: in relay mode the rate changes with the setup, not with what happens in the room.

Saved as JSON (ml/model/baseline.json) so the hub can load it without extra libraries.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

FEATURE_NAMES = (
    "wobble",           # mean over subcarriers of the std over time (the viewer's activity measure)
    "relative_wobble",  # same, divided by each subcarrier's mean: insensitive to overall signal level
    "peak_wobble",      # 90th percentile of the per-subcarrier std: motion often hits some subcarriers hard
    "step_size",        # mean absolute change from one packet to the next: how fast it wobbles
)


def window_features(windows: np.ndarray) -> np.ndarray:
    """(n_windows, packets, subcarriers) amplitudes in [0, 1] -> (n_windows, len(FEATURE_NAMES))."""
    w = windows.astype(np.float64)
    live = w.mean(axis=1) > 1e-3                       # null/guard subcarriers carry nothing
    std = w.std(axis=1)
    mean = w.mean(axis=1)
    feats = []
    for i in range(len(w)):
        m = live[i]
        if not m.any():
            feats.append([0.0, 0.0, 0.0, 0.0])
            continue
        s = std[i, m]
        feats.append([
            s.mean(),
            (s / mean[i, m]).mean(),
            np.percentile(s, 90),
            np.abs(np.diff(w[i][:, m], axis=0)).mean(),
        ])
    return np.asarray(feats)


class Baseline:
    """Standardised features -> multinomial logistic regression (L2), trained by gradient descent."""

    def __init__(self, classes: list[int], mu=None, sigma=None, W=None, b=None):
        self.classes = list(classes)
        self.mu, self.sigma, self.W, self.b = mu, sigma, W, b

    @classmethod
    def fit(cls, X: np.ndarray, y: np.ndarray, l2: float = 0.01, steps: int = 3000, lr: float = 0.3) -> "Baseline":
        classes = sorted(set(int(v) for v in y))
        model = cls(classes)
        model.mu = X.mean(axis=0)
        model.sigma = X.std(axis=0) + 1e-9
        Z = (X - model.mu) / model.sigma
        idx = np.array([classes.index(int(v)) for v in y])
        Y = np.eye(len(classes))[idx]
        # balance classes so a class with more windows does not win by default
        weight = (len(y) / (len(classes) * Y.sum(axis=0)))[idx]
        W = np.zeros((Z.shape[1], len(classes)))
        b = np.zeros(len(classes))
        for _ in range(steps):
            P = _softmax(Z @ W + b)
            G = (P - Y) * weight[:, None] / len(Z)
            W -= lr * (Z.T @ G + l2 * W)
            b -= lr * G.sum(axis=0)
        model.W, model.b = W, b
        return model

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return _softmax(((X - self.mu) / self.sigma) @ self.W + self.b)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.array(self.classes)[self.predict_proba(X).argmax(axis=1)]

    def save(self, path: Path, class_names: dict[int, str]) -> None:
        Path(path).write_text(json.dumps({
            "features": list(FEATURE_NAMES),
            "classes": [class_names[c] for c in self.classes],
            "class_ids": self.classes,
            "mu": self.mu.tolist(), "sigma": self.sigma.tolist(),
            "W": self.W.tolist(), "b": self.b.tolist(),
        }, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Baseline":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(d["class_ids"], np.array(d["mu"]), np.array(d["sigma"]), np.array(d["W"]), np.array(d["b"]))


def _softmax(a: np.ndarray) -> np.ndarray:
    e = np.exp(a - a.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)
