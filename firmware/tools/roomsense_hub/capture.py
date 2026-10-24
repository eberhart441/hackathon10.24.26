"""Record labeled raw CSI from one or more node serial ports to CSV (Training mode).

Training mode (requirements 17 and 21.5) is restricted: the installer must be on
the allowlist, and each file holds one class. Raw CSI is written to disk only by this tool.

Example:
    rs-capture --port COM5 --port COM7 --label moving --installer alice
"""
from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .ingest import CsvSink, Ingest

CLASSES = ("empty", "moving", "still_present")
DEFAULT_ALLOWLIST = Path(__file__).resolve().parent.parent / "authorized_installers.txt"


class CaptureError(Exception):
    """A problem the user can fix (not a bug)."""


def load_allowlist(path: Path) -> set[str]:
    if not path.is_file():
        raise CaptureError(
            f"No installer allowlist at {path}. Copy authorized_installers.example.txt to "
            "authorized_installers.txt and list the two authorized installers."
        )
    names = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            names.add(line.lower())
    return names


def check_training_allowed(installer: str, allowlist_path: Path) -> None:
    if installer.strip().lower() not in load_allowlist(allowlist_path):
        raise CaptureError(f"'{installer}' is not an authorized installer for Training mode.")


def output_paths(out_dir: Path, label: str, now: datetime) -> tuple[Path, Path]:
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    base = out_dir / f"{label}_{stamp}"
    return base.with_suffix(".csv"), base.with_suffix(".meta.json")


def _reader(port: str, baud: int, lines: "queue.Queue[tuple[str, float, str]]", stop: threading.Event) -> None:
    import serial  # imported here so the rest of the package works without pyserial

    try:
        with serial.Serial(port, baud, timeout=0.2) as ser:
            while not stop.is_set():
                raw = ser.readline()
                if raw:
                    lines.put((port, time.time(), raw.decode("utf-8", errors="replace")))
    except serial.SerialException as exc:
        lines.put((port, time.time(), f"#ERROR {exc}"))


def run_capture(args: argparse.Namespace) -> int:
    allowlist = Path(args.allowlist)
    check_training_allowed(args.installer, allowlist)

    now = datetime.now(timezone.utc)
    csv_path, meta_path = output_paths(Path(args.out), args.label, now)
    sink = CsvSink.open(csv_path)
    ingest = Ingest(sink=sink)
    meta = {
        "label": args.label,
        "installer": args.installer,
        "started_utc": now.isoformat(),
        "ports": args.port,
        "baud": args.baud,
        "note": args.note,
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    lines: "queue.Queue[tuple[str, float, str]]" = queue.Queue()
    stop = threading.Event()
    threads = [threading.Thread(target=_reader, args=(p, args.baud, lines, stop), daemon=True) for p in args.port]
    for t in threads:
        t.start()

    print(f"Recording '{args.label}' to {csv_path}  (Ctrl+C to stop)")
    deadline = time.time() + args.duration if args.duration else None
    next_report = time.time() + 2.0
    try:
        while deadline is None or time.time() < deadline:
            try:
                port, arrival, text = lines.get(timeout=0.2)
            except queue.Empty:
                text = None
            if text is not None:
                if text.startswith("#ERROR"):
                    print(f"{port}: {text[7:]}", file=sys.stderr)
                    break
                ingest.feed_line(text, arrival)
            if time.time() >= next_report:
                next_report = time.time() + 2.0
                _print_status(ingest, sink)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        sink.close()
        meta.update(rows=sink.rows, ended_utc=datetime.now(timezone.utc).isoformat(),
                    streams=[s.__dict__ for s in ingest.stream_stats()])
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Saved {sink.rows} CSI rows to {csv_path}" + (f" ({sink.skipped} skipped: different n_sub)" if sink.skipped else ""))
    return 0


def _print_status(ingest: Ingest, sink: CsvSink) -> None:
    parts = [f"rows={sink.rows}"]
    for s in ingest.stream_stats():
        parts.append(f"{s.node_id}: got={s.received} lost={s.lost} ({s.loss_rate:.1%})")
    late = ingest.offline_nodes(time.time())
    if late:
        parts.append("NO HEARTBEAT: " + ",".join(late))
    print(" | ".join(parts))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", action="append", required=True, help="serial port (repeat for several nodes)")
    p.add_argument("--baud", type=int, default=921600)
    p.add_argument("--label", required=True, choices=CLASSES, help="one class per file")
    p.add_argument("--installer", required=True, help="authorized installer name")
    p.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "data"))
    p.add_argument("--duration", type=float, default=0.0, help="seconds to record (0 = until Ctrl+C)")
    p.add_argument("--note", default="", help="free-text note saved in the meta file")
    p.add_argument("--allowlist", default=str(DEFAULT_ALLOWLIST))
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_capture(args)
    except CaptureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
