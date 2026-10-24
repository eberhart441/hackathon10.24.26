"""Convert a trained Keras model to TensorFlow Lite (TinyML deployment).

Two output formats:
  1. Float32 TFLite  — same accuracy as the Keras model, smaller file, faster
     inference. Good for a Pi or a phone.
  2. INT8 quantized  — weights AND activations quantized to 8-bit integers.
     Required for microcontrollers (ESP32-S3 with TFLite Micro, Arduino, etc.).
     Needs a small representative dataset for calibration.

The INT8 model can be further converted to a C array so it can be compiled
directly into firmware (see the printed instructions at the end).

Usage:
    # Float32 only (no data needed):
    python -m ml.convert --model ml/model/csi_motion_model.keras

    # INT8 quantized (recommended for MCU — needs calibration data):
    python -m ml.convert --model ml/model/csi_motion_model.keras \\
        --manifest firmware/tools/data/manifest.csv --quantize

Output files (written next to the source model):
    csi_motion_model.tflite          (float32)
    csi_motion_model_int8.tflite     (int8, only with --quantize)
    csi_motion_model_int8.cc         (C array, only with --quantize)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
DATA_DIR = _ROOT / "firmware" / "tools" / "data"  # where rs-record saves sessions

from ml.features import (
    LABEL_TO_INT,
    N_SUB,
    WINDOW_PACKETS,
    apply_scaler,
    extract_windows,
    load_session_csv,
)


def make_representative_dataset(manifest_path: Path, data_dir: Path,
                                 scaler_path: Path, n_samples: int = 200):
    """Yield calibration batches for INT8 quantization.

    Uses training sessions only — no test data leaks into calibration.
    """
    import pandas as pd

    npz    = np.load(str(scaler_path))
    scaler = {"mean": npz["mean"], "std": npz["std"]}
    manifest = pd.read_csv(manifest_path, dtype=str)
    train_rows = manifest[manifest["split"] == "train"]

    all_windows = []
    for _, row in train_rows.iterrows():
        csv_file = data_dir / row["file"]
        if row["label"] not in LABEL_TO_INT or not csv_file.is_file():
            continue
        wins = extract_windows(load_session_csv(csv_file))
        if len(wins) > 0:
            all_windows.append(apply_scaler(wins, scaler))

    if not all_windows:
        raise RuntimeError("No training CSVs found for calibration. "
                           "Run ml/train.py first and record sessions.")

    combined = np.concatenate(all_windows)
    rng      = np.random.default_rng(42)
    samples  = combined[rng.permutation(len(combined))[:n_samples]].astype(np.float32)

    def generator():
        for w in samples:
            yield [w[np.newaxis, :, :]]   # shape (1, WINDOW_PACKETS, N_SUB)

    return generator


def convert_float32(model_path: Path, out_path: Path) -> None:
    import tensorflow as tf
    converter = tf.lite.TFLiteConverter.from_keras_model(
        tf.keras.models.load_model(str(model_path)))
    data = converter.convert()
    out_path.write_bytes(data)
    print(f"Float32 TFLite: {out_path}  ({len(data)/1024:.1f} KB)")


def convert_int8(model_path: Path, out_path: Path,
                 manifest_path: Path, data_dir: Path, scaler_path: Path) -> None:
    import tensorflow as tf

    converter = tf.lite.TFLiteConverter.from_keras_model(
        tf.keras.models.load_model(str(model_path)))
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = make_representative_dataset(
        manifest_path, data_dir, scaler_path)
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    # Keep input/output as float32 for ease of use from Python.
    # Set both to tf.int8 if targeting TFLite Micro on ESP32.

    data = converter.convert()
    out_path.write_bytes(data)
    print(f"INT8 TFLite:    {out_path}  ({len(data)/1024:.1f} KB)")


def to_c_array(tflite_path: Path, c_path: Path) -> None:
    """Write the .tflite flatbuffer as a C byte array for firmware inclusion."""
    data     = tflite_path.read_bytes()
    var_name = tflite_path.stem.replace("-", "_").replace(".", "_")
    hex_bytes = ", ".join(f"0x{b:02x}" for b in data)
    c_code = (
        f"// Auto-generated from {tflite_path.name} — do not edit.\n"
        f"// Include in your firmware project and link against TFLite Micro.\n\n"
        f"#include <stdint.h>\n\n"
        f"alignas(8) const uint8_t {var_name}[] = {{\n  {hex_bytes}\n}};\n"
        f"const unsigned int {var_name}_len = {len(data)};\n"
    )
    c_path.write_text(c_code, encoding="utf-8")
    print(f"C array:        {c_path}  ({len(data)} bytes, variable: {var_name})")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model",    required=True)
    parser.add_argument("--scaler",   default="")
    parser.add_argument("--manifest", default=str(DATA_DIR / "manifest.csv"))
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument("--quantize", action="store_true",
                        help="produce INT8 quantized model (recommended for MCU)")
    parser.add_argument("--out-dir",  default="")
    args = parser.parse_args(argv)

    model_path = Path(args.model)
    if not model_path.is_file():
        print(f"error: model not found: {model_path}", file=sys.stderr)
        return 1

    out_dir     = Path(args.out_dir) if args.out_dir else model_path.parent
    scaler_path = Path(args.scaler) if args.scaler else model_path.parent / "scaler.npz"
    data_dir    = Path(args.data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    fp32_path = out_dir / "csi_motion_model.tflite"
    convert_float32(model_path, fp32_path)

    if args.quantize:
        if not scaler_path.is_file():
            print(f"error: scaler not found at {scaler_path}", file=sys.stderr)
            return 1
        int8_path = out_dir / "csi_motion_model_int8.tflite"
        cc_path   = out_dir / "csi_motion_model_int8.cc"
        convert_int8(model_path, int8_path, Path(args.manifest), data_dir, scaler_path)
        to_c_array(int8_path, cc_path)

        print("\n── Next steps for MCU deployment ──────────────────────────────────")
        print("1. Copy csi_motion_model_int8.cc into your firmware project.")
        print("2. Add TFLite Micro to idf_component.yml:")
        print("     espressif/esp-tflite-micro")
        print("3. Declare the model in firmware:")
        print("     extern const uint8_t csi_motion_model_int8[];")
        print("     extern const unsigned int csi_motion_model_int8_len;")
        print("4. Input tensor shape: [1, 150, 64]  (batch, window, subcarriers)")
        print("5. Z-score normalise input with mean[]/std[] from scaler.npz (64 floats each).")
        print("6. Output: 3 floats (softmax) → argmax → class index")
        print("   0=no_motion_seen  1=motion  2=doorway_crossing")
    else:
        print("\nTip: re-run with --quantize to produce the INT8 MCU-ready model.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
