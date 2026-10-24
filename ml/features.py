"""Windowing and feature extraction for CSI motion classification.

This module is the shared feature pipeline: it runs both during training
(ml/train.py, ml/eval.py) and at inference time on the Pi (pi/room_state.py).
Keep it pure — no file I/O, no model loading, no side effects.

Input: a session DataFrame as written by CsvSink (firmware/tools/beacon_hub/ingest.py).

CSV columns:
    arrival_unix_s, node_id, tx_mac, seq, ts_us, rssi_dbm, channel,
    a0, a1, ..., a63   (64 amplitude values)

tx_mac is stripped here and never passed downstream (data rules, validation plan §2).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ── Column layout ──────────────────────────────────────────────────────────────
N_SUB = 64                        # amplitudes per CSI record (firmware sends 64)
AMP_COLS = [f"a{i}" for i in range(N_SUB)]

# ── Windowing ─────────────────────────────────────────────────────────────────
WINDOW_PACKETS = 150              # 1.5 s at 100 pps (validation plan §4)
STEP_PACKETS   = 75               # 50 % overlap

# ── Median filter ─────────────────────────────────────────────────────────────
MEDIAN_KERNEL  = 5                # packets; must be odd. Kills single-packet spikes
                                  # without blurring motion transitions (< 0.05 s blur)

# Label encoding (matches validation plan §1 / record_session.py LABELS)
LABEL_NAMES  = ("no_motion_seen", "motion", "doorway_crossing")
LABEL_TO_INT = {name: idx for idx, name in enumerate(LABEL_NAMES)}
INT_TO_LABEL = {idx: name for name, idx in LABEL_TO_INT.items()}
N_CLASSES    = len(LABEL_NAMES)


def median_filter_amplitudes(df: pd.DataFrame, kernel: int = MEDIAN_KERNEL) -> pd.DataFrame:
    """Apply a per-subcarrier median filter along the time axis.

    Replaces each amplitude value with the median of the surrounding `kernel`
    packets (same subcarrier).  Impulsive single-packet spikes — hardware glitches,
    multipath bursts — are replaced by the local median, leaving slower motion
    transitions intact.

    Args:
        df:     Session DataFrame with AMP_COLS present (float or int).
        kernel: Window size in packets.  Must be odd; clipped to at least 3.
                Larger = more smoothing but slightly more edge blur.

    Returns a new DataFrame with the amplitude columns replaced; all other
    columns are unchanged.
    """
    if kernel < 3:
        kernel = 3
    if kernel % 2 == 0:
        kernel += 1          # enforce odd so the window is symmetric

    amps = df[AMP_COLS].values.astype(np.float32)
    n, _ = amps.shape
    half = kernel // 2
    out  = np.empty_like(amps)

    for t in range(n):
        lo = max(0, t - half)
        hi = min(n, t + half + 1)
        out[t] = np.median(amps[lo:hi], axis=0)

    result = df.copy()
    result[AMP_COLS] = out
    return result


def load_session_csv(path: str | "os.PathLike", smooth: bool = True) -> pd.DataFrame:
    """Read one session CSV and return a clean DataFrame.

    - Strips tx_mac (privacy rule).
    - Coerces amplitude columns to uint8.
    - Sorts by seq to handle any out-of-order arrival.
    - Applies a median filter to kill single-packet spikes (smooth=True by default).
    - Does NOT filter by node — caller chooses which node(s) to use.
    """
    df = pd.read_csv(path, dtype=str)

    # Strip MAC so it never reaches downstream code
    df = df.drop(columns=["tx_mac"], errors="ignore")

    numeric = ["arrival_unix_s", "seq", "ts_us", "rssi_dbm", "channel"] + AMP_COLS
    for col in numeric:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=AMP_COLS)
    df[AMP_COLS] = df[AMP_COLS].astype(np.uint8)
    df = df.sort_values("seq").reset_index(drop=True)

    if smooth:
        df = median_filter_amplitudes(df)

    return df


def extract_windows(
    df: pd.DataFrame,
    window: int = WINDOW_PACKETS,
    step: int   = STEP_PACKETS,
) -> np.ndarray:
    """Slide a window over the amplitude columns of one session.

    Returns shape (n_windows, window, N_SUB), dtype float32, values in [0, 1].
    Windows are built inside one session only — never across sessions (leakage rule §4).
    """
    amps = df[AMP_COLS].values.astype(np.float32) / 255.0   # normalise to [0, 1]
    n = len(amps)
    if n < window:
        return np.empty((0, window, N_SUB), dtype=np.float32)

    starts = range(0, n - window + 1, step)
    return np.stack([amps[s : s + window] for s in starts], axis=0)


def variance_features(windows: np.ndarray) -> np.ndarray:
    """Per-subcarrier variance across time, shape (n_windows, N_SUB).

    Used as the simple baseline (validation plan §6 sanity checks).
    """
    return windows.var(axis=1)


def fit_scaler(windows: np.ndarray) -> dict:
    """Compute mean and std on training windows (shape N_windows × W × N_SUB).

    Call this on training data only, then pass the result to `apply_scaler`.
    """
    flat = windows.reshape(-1, N_SUB)
    return {"mean": flat.mean(axis=0), "std": flat.std(axis=0) + 1e-8}


def apply_scaler(windows: np.ndarray, scaler: dict) -> np.ndarray:
    """Z-score normalise windows with a pre-fitted scaler (no data leakage)."""
    return (windows - scaler["mean"]) / scaler["std"]
