"""Leave-One-Session-Out (LOSO) evaluation for the CSI motion classifier.

Reads train + val sessions from the manifest, runs LOSO cross-validation,
reports per-class metrics and a confusion matrix, then scores the held-out
test sessions once with the final model.

Usage:
    python -m ml.eval
    python -m ml.eval --manifest data/manifest.csv --model ml/model/csi_motion_model.keras

If --model is omitted the script trains a fresh model on each fold (pure LOSO).
If --model is given it evaluates that saved model on the test split only (final report mode).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

from ml.features import (
    INT_TO_LABEL,
    LABEL_TO_INT,
    N_CLASSES,
    N_SUB,
    WINDOW_PACKETS,
    apply_scaler,
    fit_scaler,
)
from ml.train import build_model, load_sessions


def load_all_sessions(manifest: pd.DataFrame, splits: list[str], data_dir: Path):
    rows = manifest[manifest["split"].isin(splits)]
    X, y, s = load_sessions(rows, data_dir)
    return X, y, np.array(s)


def confusion_matrix_str(cm: np.ndarray) -> str:
    header = f"{'':22s}" + "".join(f"{INT_TO_LABEL[j]:>22s}" for j in range(N_CLASSES))
    lines  = [header]
    for i in range(N_CLASSES):
        row = f"{INT_TO_LABEL[i]:22s}" + "".join(f"{cm[i,j]:>22d}" for j in range(N_CLASSES))
        lines.append(row)
    return "\n".join(lines)


def class_report(y_true: np.ndarray, y_pred: np.ndarray) -> str:
    lines = [f"{'class':22s}  {'precision':>10s}  {'recall':>10s}  {'f1':>10s}  {'support':>8s}"]
    f1s = []
    for i in range(N_CLASSES):
        tp = int(((y_pred == i) & (y_true == i)).sum())
        fp = int(((y_pred == i) & (y_true != i)).sum())
        fn = int(((y_pred != i) & (y_true == i)).sum())
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        f1s.append(f1)
        lines.append(f"{INT_TO_LABEL[i]:22s}  {prec:>10.3f}  {rec:>10.3f}  {f1:>10.3f}  {(tp+fn):>8d}")
    macro_f1 = float(np.mean(f1s))
    lines.append(f"\n{'macro-F1':22s}  {'':>10s}  {'':>10s}  {macro_f1:>10.3f}")
    i_motion = LABEL_TO_INT["motion"]
    i_no     = LABEL_TO_INT["no_motion_seen"]
    missed   = int(((y_pred == i_no) & (y_true == i_motion)).sum())
    total_m  = int((y_true == i_motion).sum())
    lines.append(
        f"\nKey error — missed motion (motion → no_motion_seen): "
        f"{missed}/{total_m} = {missed/total_m:.1%}" if total_m else
        "\nKey error — missed motion: no motion windows in set"
    )
    return "\n".join(lines)


def loso_eval(X, y, sessions, epochs, batch_size):
    unique = np.unique(sessions)
    y_true_all, y_pred_all, fold_f1s = [], [], []

    for fold_idx, held_out in enumerate(unique):
        mask_val   = sessions == held_out
        mask_train = ~mask_val
        X_tr, y_tr = X[mask_train], y[mask_train]
        X_va, y_va = X[mask_val],   y[mask_val]

        if len(np.unique(y_tr)) < N_CLASSES:
            print(f"  fold {fold_idx+1}/{len(unique)} held={held_out}: "
                  "not all classes in train, skipping.")
            continue

        scaler = fit_scaler(X_tr)
        X_tr   = apply_scaler(X_tr, scaler)
        X_va   = apply_scaler(X_va, scaler)

        import tensorflow as tf
        model = build_model()
        model.fit(X_tr, y_tr, validation_data=(X_va, y_va),
                  epochs=epochs, batch_size=batch_size, verbose=0,
                  callbacks=[tf.keras.callbacks.EarlyStopping(
                      patience=5, restore_best_weights=True, monitor="val_loss")])

        y_pred = model.predict(X_va, verbose=0).argmax(axis=1)
        f1s = []
        for i in range(N_CLASSES):
            tp = int(((y_pred == i) & (y_va == i)).sum())
            fp = int(((y_pred == i) & (y_va != i)).sum())
            fn = int(((y_pred != i) & (y_va == i)).sum())
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
            f1s.append(f1)
        fold_macro = float(np.mean(f1s))
        fold_f1s.append(fold_macro)
        print(f"  fold {fold_idx+1}/{len(unique)} held={held_out:8s}  macro-F1={fold_macro:.3f}")
        y_true_all.append(y_va)
        y_pred_all.append(y_pred)
        tf.keras.backend.clear_session()

    y_true_all = np.concatenate(y_true_all) if y_true_all else np.array([], dtype=np.int32)
    y_pred_all = np.concatenate(y_pred_all) if y_pred_all else np.array([], dtype=np.int32)
    return y_true_all, y_pred_all, fold_f1s


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest",   default=str(_ROOT / "data" / "manifest.csv"))
    parser.add_argument("--data-dir",   default=str(_ROOT / "data"))
    parser.add_argument("--model",      default="")
    parser.add_argument("--scaler",     default="")
    parser.add_argument("--epochs",     type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    data_dir      = Path(args.data_dir)

    if not manifest_path.is_file():
        print(f"error: manifest not found at {manifest_path}", file=sys.stderr)
        return 1

    manifest = pd.read_csv(manifest_path, dtype=str)

    if args.model:
        import tensorflow as tf
        model = tf.keras.models.load_model(args.model)
        scaler_path = Path(args.scaler) if args.scaler else Path(args.model).parent / "scaler.npz"
        npz    = np.load(str(scaler_path))
        scaler = {"mean": npz["mean"], "std": npz["std"]}

        print("\n=== TEST SET (final, one-time score) ===")
        X_test, y_test, _ = load_all_sessions(manifest, ["test"], data_dir)
        if len(X_test) == 0:
            print("No test sessions found.")
            return 1
        y_pred = model.predict(apply_scaler(X_test, scaler), verbose=0).argmax(axis=1)
        cm = np.zeros((N_CLASSES, N_CLASSES), dtype=int)
        for t, p in zip(y_test, y_pred):
            cm[t, p] += 1
        print("\nConfusion matrix (rows=true, cols=predicted):")
        print(confusion_matrix_str(cm))
        print("\nPer-class report:")
        print(class_report(y_test, y_pred))
        return 0

    print("Loading train + val sessions for LOSO …")
    X, y, sessions = load_all_sessions(manifest, ["train", "val"], data_dir)
    if len(X) == 0:
        print("error: no data found.", file=sys.stderr)
        return 1
    print(f"  {len(X)} windows, {len(np.unique(sessions))} sessions\n")

    print("=== LOSO cross-validation ===")
    y_true, y_pred, fold_f1s = loso_eval(X, y, sessions, args.epochs, args.batch_size)

    if not fold_f1s:
        print("No folds completed.")
        return 1

    print(f"\nMacro-F1 per fold: {[f'{v:.3f}' for v in fold_f1s]}")
    print(f"Mean macro-F1: {np.mean(fold_f1s):.3f}  std: {np.std(fold_f1s):.3f}")

    cm = np.zeros((N_CLASSES, N_CLASSES), dtype=int)
    for t, p in zip(y_true, y_pred):
        cm[t, p] += 1
    print("\nConfusion matrix (rows=true, cols=predicted):")
    print(confusion_matrix_str(cm))
    print("\nPer-class report:")
    print(class_report(y_true, y_pred))

    majority_class = int(np.bincount(y).argmax())
    maj_acc = float((y_true == majority_class).mean())
    print(f"\nBaseline — majority class ({INT_TO_LABEL[majority_class]}): {maj_acc:.3f}")
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler as SkScaler
        vf  = X.var(axis=1).mean(axis=1, keepdims=True)
        sc  = SkScaler().fit(vf)
        clf = LogisticRegression(max_iter=500).fit(sc.transform(vf), y)
        print(f"Baseline — variance threshold (logistic): {clf.score(sc.transform(vf), y):.3f}")
    except ImportError:
        print("(sklearn not installed; variance baseline skipped)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
