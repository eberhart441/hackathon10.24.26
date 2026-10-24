"""Train a 1-D CNN motion classifier on labeled CSI session CSVs.

Reads sessions from firmware/tools/data/manifest.csv (written by rs-record).  You only need 'train' sessions —
if no 'val' sessions exist the script automatically holds out one session
per class from training for validation (auto-CV mode).  If you do have
explicit 'val' rows in the manifest those are used instead.

Usage:
    # Only record --split train sessions, val is chosen automatically:
    python -m ml.train

    # Or point at a specific manifest / output dir:
    python -m ml.train --manifest firmware/tools/data/manifest.csv --out ml/model --epochs 30

The model input shape is (WINDOW_PACKETS, N_SUB) = (150, 64).
Output is a 3-class softmax over [no_motion_seen, motion, doorway_crossing].
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
DATA_DIR = _ROOT / "firmware" / "tools" / "data"  # where rs-record saves sessions

from ml.features import (
    INT_TO_LABEL,
    LABEL_TO_INT,
    N_CLASSES,
    N_SUB,
    WINDOW_PACKETS,
    apply_scaler,
    extract_windows,
    fit_scaler,
    load_session_csv,
    median_filter_amplitudes,
)


# ── Model definition ──────────────────────────────────────────────────────────

def build_model(window: int = WINDOW_PACKETS, n_sub: int = N_SUB, n_classes: int = N_CLASSES):
    """1-D CNN over the time axis.

    Architecture:
    - Input: (window, 64) amplitude spectrogram.
    - Two Conv1D layers extract temporal patterns across subcarriers.
    - GlobalAveragePooling collapses time so window length can vary at inference.
    - Dense + Dropout before the softmax head.
    """
    import tensorflow as tf
    from tensorflow import keras

    inp = keras.Input(shape=(window, n_sub), name="csi_window")
    x = keras.layers.Conv1D(32, kernel_size=5, padding="same", activation="relu")(inp)
    x = keras.layers.BatchNormalization()(x)
    x = keras.layers.Conv1D(64, kernel_size=5, padding="same", activation="relu")(x)
    x = keras.layers.BatchNormalization()(x)
    x = keras.layers.Conv1D(64, kernel_size=3, padding="same", activation="relu")(x)
    x = keras.layers.GlobalAveragePooling1D()(x)
    x = keras.layers.Dense(128, activation="relu")(x)
    x = keras.layers.Dropout(0.4)(x)
    out = keras.layers.Dense(n_classes, activation="softmax", name="class_probs")(x)

    model = keras.Model(inp, out, name="csi_motion_classifier")
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=1e-3),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model


# ── Data loading ──────────────────────────────────────────────────────────────

def load_sessions(rows: pd.DataFrame, data_dir: Path, tag: str = ""):
    """Load a set of manifest rows into (windows, labels, session_ids)."""
    all_windows, all_labels, all_sessions = [], [], []

    for _, row in rows.iterrows():
        session_id = row["session_id"]
        label_str  = row["label"]
        csv_file   = data_dir / row["file"]

        if label_str not in LABEL_TO_INT:
            print(f"  WARNING: unknown label '{label_str}' in {session_id}, skipping.")
            continue
        if not csv_file.is_file():
            print(f"  WARNING: {csv_file} not found, skipping {session_id}.")
            continue

        # A session recorded through a relay gateway holds several receivers. Window each one on
        # its own (as the live hub does); mixed together, the windows would alternate between
        # receivers packet by packet and the model would learn the mix, not the motion.
        df   = load_session_csv(csv_file, smooth=False)
        per_node = [extract_windows(median_filter_amplitudes(g.reset_index(drop=True)))
                    for _, g in df.groupby("node_id")] if "node_id" in df.columns else                    [extract_windows(median_filter_amplitudes(df))]
        per_node = [w for w in per_node if len(w)]
        wins = np.concatenate(per_node) if per_node else np.empty((0, WINDOW_PACKETS, N_SUB), dtype=np.float32)
        if len(wins) == 0:
            print(f"  WARNING: {session_id} produced 0 windows (too short?), skipping.")
            continue

        label_int = LABEL_TO_INT[label_str]
        all_windows.append(wins)
        all_labels.append(np.full(len(wins), label_int, dtype=np.int32))
        all_sessions.extend([session_id] * len(wins))
        marker = f"[{tag}]" if tag else ""
        print(f"  {session_id:6s}  {label_str:20s}  {len(wins):4d} windows {marker}")

    if not all_windows:
        return (np.empty((0, WINDOW_PACKETS, N_SUB), dtype=np.float32),
                np.empty(0, dtype=np.int32), [])

    return (np.concatenate(all_windows),
            np.concatenate(all_labels),
            all_sessions)


def auto_split_val(manifest: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hold out the last session per class from 'train' rows as a validation set.

    Called when the manifest has no 'val' rows at all.  The held-out sessions
    are NOT written back to the manifest — they stay marked as 'train' on disk.
    """
    train_rows = manifest[manifest["split"] == "train"].copy()
    val_idx: list[int] = []

    for label in train_rows["label"].unique():
        label_rows = train_rows[train_rows["label"] == label]
        if len(label_rows) < 2:
            print(f"  WARNING: only 1 '{label}' session — it will be used for both "
                  "train and val. Record more sessions for a clean split.")
        val_idx.append(label_rows.index[-1])

    val_rows   = train_rows.loc[val_idx]
    train_rows = train_rows.drop(index=val_idx)
    return train_rows, val_rows


# ── Baseline ──────────────────────────────────────────────────────────────────

def train_baseline(X_train, y_train, X_val, y_val, train_rows, val_rows, data_dir: Path, out_dir: Path) -> int:
    """Fit the simple baseline, report val and leave-one-session-out accuracy, save it as JSON."""
    from .baseline import FEATURE_NAMES, Baseline, window_features

    print("Model: baseline (features: " + ", ".join(FEATURE_NAMES) + "; logistic regression)\n")
    F_train = window_features(X_train)
    model = Baseline.fit(F_train, y_train)
    print(f"Train accuracy: {(model.predict(F_train) == y_train).mean():.3f}")
    val_acc = None
    if len(X_val) > 0:
        val_acc = (model.predict(window_features(X_val)) == y_val).mean()

    # Leave one session out: train on all other sessions, test on the left-out one. With only a
    # few sessions this is a fairer number than a single held-out pair.
    print("\nLeave-one-session-out (each session tested by a model that never saw it):")
    X_all, y_all, sessions = load_sessions(pd.concat([train_rows, val_rows]), data_dir)
    F_all, sessions = window_features(X_all), np.array(sessions)
    correct = total = 0
    for s in dict.fromkeys(sessions):
        test = sessions == s
        if len(set(y_all[~test])) < 2:
            print(f"  {s:6s}  skipped (no other session to compare against)")
            continue
        m = Baseline.fit(F_all[~test], y_all[~test])
        hit = (m.predict(F_all[test]) == y_all[test])
        correct, total = correct + hit.sum(), total + len(hit)
        print(f"  {s:6s}  {INT_TO_LABEL[int(y_all[test][0])]:20s}  {hit.mean():.3f}  ({hit.sum()}/{len(hit)} windows)")
    if total:
        print(f"  overall: {correct / total:.3f}")

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "baseline.json"
    model.save(path, INT_TO_LABEL)
    print(f"\nModel saved  → {path}")
    if val_acc is not None:
        print(f"Final val accuracy: {val_acc:.3f}")
    print("\nNote: few sessions, one person, one layout. Record more (different people, paths, both rooms) "
          "before trusting these numbers.")
    return 0


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest",   default=str(DATA_DIR / "manifest.csv"))
    parser.add_argument("--data-dir",   default=str(DATA_DIR))
    parser.add_argument("--out",        default=str(_HERE / "model"))
    parser.add_argument("--epochs",     type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--model", choices=("baseline", "cnn"), default="baseline",
                        help="baseline (default): 4 wobble features + logistic regression, no TensorFlow. "
                             "cnn: the 1-D CNN, needs far more recorded sessions")
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    data_dir      = Path(args.data_dir)
    out_dir       = Path(args.out)

    if not manifest_path.is_file():
        print(f"error: manifest not found at {manifest_path}", file=sys.stderr)
        print("Record sessions first with:  rs-record --port <PORT> --label <LABEL> "
              "--split train --person A", file=sys.stderr)
        return 1

    manifest = pd.read_csv(manifest_path, dtype=str)
    print(f"Manifest: {len(manifest)} sessions total")

    has_explicit_val = (manifest["split"] == "val").any()

    if has_explicit_val:
        print("\nUsing explicit val sessions from manifest.")
        train_rows = manifest[manifest["split"] == "train"]
        val_rows   = manifest[manifest["split"] == "val"]
    else:
        print("\nNo val sessions in manifest — auto-holding out last session per "
              "class from train for validation.")
        train_rows, val_rows = auto_split_val(manifest)
        print(f"  Auto-val sessions: {list(val_rows['session_id'])}")

    print("\nLoading train:")
    X_train, y_train, _ = load_sessions(train_rows, data_dir, tag="train")
    print(f"  → {len(X_train)} windows\n")

    print("Loading val:")
    X_val, y_val, _ = load_sessions(val_rows, data_dir, tag="val")
    print(f"  → {len(X_val)} windows\n")

    if len(X_train) == 0:
        print("error: no training data found.", file=sys.stderr)
        return 1

    if args.model == "baseline":
        return train_baseline(X_train, y_train, X_val, y_val, train_rows, val_rows, data_dir, out_dir)

    scaler  = fit_scaler(X_train)
    X_train = apply_scaler(X_train, scaler)
    if len(X_val) > 0:
        X_val = apply_scaler(X_val, scaler)

    print("Class distribution (train windows):")
    for i, name in INT_TO_LABEL.items():
        print(f"  {i}  {name:20s}  {int((y_train == i).sum())}")

    import tensorflow as tf
    print(f"\nTensorFlow {tf.__version__}")

    model = build_model()
    model.summary()

    monitor   = "val_loss" if len(X_val) > 0 else "loss"
    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor=monitor, patience=5, restore_best_weights=True, verbose=1),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor=monitor, factor=0.5, patience=3, verbose=1),
    ]

    history = model.fit(
        X_train, y_train,
        validation_data=(X_val, y_val) if len(X_val) > 0 else None,
        epochs=args.epochs,
        batch_size=args.batch_size,
        callbacks=callbacks,
        verbose=1,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    model_path  = out_dir / "csi_motion_model.keras"
    scaler_path = out_dir / "scaler.npz"
    model.save(str(model_path))
    np.savez(str(scaler_path), mean=scaler["mean"], std=scaler["std"])
    print(f"\nModel saved  → {model_path}")
    print(f"Scaler saved → {scaler_path}")

    final_val_acc = history.history.get("val_accuracy", [None])[-1]
    if final_val_acc is not None:
        print(f"Final val accuracy: {final_val_acc:.3f}")

    if not has_explicit_val:
        print("\nNote: val was auto-selected from train sessions. For a more honest "
              "estimate, record dedicated --split val sessions and re-run.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
