"""Record one labelled validation/training session and add it to data/manifest.csv.

Builds on the capture tool (same CSV sink, consent flag required, no installer allowlist) and
adds a session ID, a countdown, and a manifest row so sessions can be split by
session for validation and cross-validation.

Labels are model classes, not room states. "no_motion_seen" is not a claim that the
room is empty.

Example:
    rs-record --port COM5 --label motion --person A --layout L1 --motion-desc slow_walk \\
        --split train --consent
"""
from __future__ import annotations

import argparse
import csv
import json
import queue
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .capture import CaptureError, _reader
from .ingest import CsvSink, Ingest

LABELS = ("no_motion_seen", "motion", "doorway_crossing")
SPLITS = ("train", "val", "test")
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data"
MANIFEST_COLUMNS = [
    "session_id", "label", "person", "layout", "path_or_speed", "date",
    "duration_s", "rows", "split", "file",
]


def next_session_id(manifest: Path) -> str:
    """S01, S02, ... one past the highest ID already in the manifest."""
    highest = 0
    if manifest.is_file():
        with manifest.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sid = row.get("session_id", "")
                if sid.startswith("S") and sid[1:].isdigit():
                    highest = max(highest, int(sid[1:]))
    return f"S{highest + 1:02d}"


def append_manifest(manifest: Path, row: dict) -> None:
    new = not manifest.is_file()
    with manifest.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in MANIFEST_COLUMNS})


def record(args: argparse.Namespace) -> int:
    if not args.consent:
        raise CaptureError("Recording requires --consent: only consenting team members may be recorded.")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "manifest.csv"
    session_id = args.session_id or next_session_id(manifest)
    csv_path = out / f"{session_id}_{args.label}.csv"
    if csv_path.exists():
        raise CaptureError(f"{csv_path.name} already exists; pick another --session-id.")

    print(f"Session {session_id}: label={args.label} split={args.split} person={args.person} "
          f"layout={args.layout} motion={args.motion_desc} duration={args.duration:.0f}s")
    for remaining in range(int(args.lead_in), 0, -1):
        print(f"  starting in {remaining}...", end="\r", flush=True)
        time.sleep(1)
    print(" " * 30, end="\r")

    sink = CsvSink.open(csv_path)
    ingest = Ingest(sink=sink)
    lines: "queue.Queue[tuple[str, float, str]]" = queue.Queue()
    stop = threading.Event()
    for p in args.port:
        threading.Thread(target=_reader, args=(p, args.baud, lines, stop), daemon=True).start()

    started = datetime.now(timezone.utc)
    t0 = time.time()
    deadline = t0 + args.duration
    next_report = t0 + 5.0
    failed = False
    print("RECORDING (Ctrl+C to stop early)")
    try:
        while time.time() < deadline:
            try:
                port, arrival, text = lines.get(timeout=0.2)
            except queue.Empty:
                text = None
            if text is not None:
                if text.startswith("#ERROR"):
                    print(f"{port}: {text[7:]}", file=sys.stderr)
                    failed = True
                    break
                ingest.feed_line(text, arrival)
            if time.time() >= next_report:
                next_report += 5.0
                stats = ", ".join(f"{s.node_id} loss={s.loss_rate:.1%}" for s in ingest.stream_stats())
                print(f"  {time.time() - t0:5.0f}s rows={sink.rows} {stats}")
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        sink.close()

    elapsed = time.time() - t0
    if failed or sink.rows == 0:
        csv_path.unlink(missing_ok=True)
        print("No usable data recorded; session discarded (no manifest row).", file=sys.stderr)
        return 1

    streams = [s.__dict__ for s in ingest.stream_stats()]
    worst_loss = max((s["loss_rate"] if isinstance(s, dict) and "loss_rate" in s else 0 for s in streams), default=0)
    csv_path.with_suffix(".meta.json").write_text(json.dumps({
        "session_id": session_id, "label": args.label, "installer": args.installer,
        "consent_confirmed": True, "started_utc": started.isoformat(),
        "ended_utc": datetime.now(timezone.utc).isoformat(), "ports": args.port,
        "note": args.note, "streams": streams,
    }, indent=2, default=str), encoding="utf-8")
    append_manifest(manifest, {
        "session_id": session_id, "label": args.label, "person": args.person,
        "layout": args.layout, "path_or_speed": args.motion_desc,
        "date": started.date().isoformat(), "duration_s": f"{elapsed:.0f}",
        "rows": sink.rows, "split": args.split, "file": csv_path.name,
    })
    print(f"Saved {sink.rows} rows to {csv_path}; manifest updated.")
    if worst_loss > 0.05:
        print(f"WARNING: packet loss {worst_loss:.1%} on a stream. Consider re-recording.", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", action="append", required=True, help="serial port (repeat for several nodes)")
    p.add_argument("--baud", type=int, default=921600)
    p.add_argument("--label", required=True, choices=LABELS)
    p.add_argument("--split", required=True, choices=SPLITS)
    p.add_argument("--person", required=True, help="teammate code such as A or B (no real names or IDs)")
    p.add_argument("--layout", default="L1", help="room/node layout code")
    p.add_argument("--motion-desc", default="", help="path or speed, e.g. slow_walk")
    p.add_argument("--duration", type=float, default=120.0, help="seconds to record (default 120)")
    p.add_argument("--lead-in", type=float, default=5.0, help="countdown seconds before recording starts")
    p.add_argument("--session-id", default="", help="override the auto S01, S02, ... ID")
    p.add_argument("--installer", default="", help="optional name of whoever is recording")
    p.add_argument("--consent", action="store_true", help="confirm everyone recorded has consented")
    p.add_argument("--note", default="")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return record(args)
    except CaptureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
