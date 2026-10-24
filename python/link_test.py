"""Live link-quality table for the ESP-NOW room nodes, read from the gateway's serial port.

    python link_test.py --list              # show COM ports
    python link_test.py COM5                # live table, Ctrl+C to stop and save
    python link_test.py --simulate          # no hardware: fake 4 nodes (one dies, one is lossy) to see the table

Per node it shows packets received vs expected (from the sequence number), loss %, signal strength
(RSSI), how long since the last packet, and the latest sensor values. It also writes every packet to
python/data/link-HHMMSS.csv so you can put real numbers in your README.

Close the Arduino Serial Monitor and the web dashboard first: only one program can hold a COM port.
"""

import argparse
import csv
import os
import random
import statistics
import sys
import time
from pathlib import Path

LOST_AFTER_S = 5.0  # a node silent this long is shown as LOST (the dashboard should use the same rule)


def parse(line: str) -> dict[str, float] | None:
    """Parse 'n=1,seq=5,pir=0,...' into numbers. Returns None for comments or lines without n and seq."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    out: dict[str, float] = {}
    for part in line.replace(" ", "").split(","):
        key, sep, val = part.partition("=")
        if not sep:
            continue
        try:
            out[key] = float(val)
        except ValueError:
            continue
    return out if "n" in out and "seq" in out else None


class Node:
    def __init__(self) -> None:
        self.rx = 0
        self.expected = 0
        self.last_seq: int | None = None
        self.reboots = 0
        self.rssi: list[float] = []
        self.last_seen = 0.0
        self.last: dict[str, float] = {}

    def update(self, row: dict[str, float], now: float) -> None:
        seq = int(row["seq"])
        if self.last_seq is None:
            self.expected += 1
        elif seq > self.last_seq:
            self.expected += seq - self.last_seq  # gaps in seq are lost packets
        else:
            self.reboots += 1  # seq went backwards: the node restarted
            self.expected += 1
        self.last_seq = seq
        self.rx += 1
        self.last_seen = now
        self.last = row
        if row.get("rssi", 0):
            self.rssi.append(row["rssi"])

    @property
    def loss_pct(self) -> float:
        return 100.0 * (1 - self.rx / self.expected) if self.expected else 0.0


def render(nodes: dict[int, Node], now: float, t0: float) -> str:
    lines = [
        f"ESP-NOW link test, running {now - t0:5.0f} s   (LOST = silent > {LOST_AFTER_S:.0f} s)",
        "",
        f"{'node':>4} {'rx':>5} {'exp':>5} {'loss%':>6} {'rssi avg/min':>13} {'age s':>6} {'pir':>3} {'rad':>3} {'sm s':>5} {'reboots':>7}  status",
    ]
    for nid in sorted(nodes):
        n = nodes[nid]
        age = now - n.last_seen
        rssi = f"{statistics.mean(n.rssi):6.0f}/{min(n.rssi):4.0f}" if n.rssi else "      n/a"
        status = "LOST" if age > LOST_AFTER_S else "ok"
        lines.append(
            f"{nid:>4} {n.rx:>5} {n.expected:>5} {n.loss_pct:>6.1f} {rssi:>13} {age:>6.1f} "
            f"{int(n.last.get('pir', 0)):>3} {int(n.last.get('rad', 0)):>3} {int(n.last.get('sm', -1)):>5} {n.reboots:>7}  {status}"
        )
    if not nodes:
        lines.append("  waiting for packets... (is the gateway plugged in and the room nodes powered?)")
    return "\n".join(lines)


def simulate(duration: float, hz: float):
    """Yield fake gateway lines. Node 2 drops ~15% of packets, node 3 dies at 60% of the run."""
    seq = {n: 0 for n in (1, 2, 3, 4)}
    t0 = time.time()
    while time.time() - t0 < duration:
        for n in seq:
            if n == 3 and time.time() - t0 > duration * 0.6:
                continue
            seq[n] += 1
            if n == 2 and random.random() < 0.15:
                continue
            rssi = random.randint(-70, -45) if n != 2 else random.randint(-85, -70)
            pir = 1 if random.random() < 0.3 else 0
            yield f"n={n},seq={seq[n]},pir={pir},rad=0,d=-1,sm={0 if pir else 7},x=0,rssi={rssi}\n"
        time.sleep(1 / hz)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--duration", type=float, default=10.0, help="seconds, only for --simulate")
    args = ap.parse_args()

    if args.list:
        from serial.tools import list_ports

        for p in list_ports.comports():
            print(f"{p.device:8} {p.description}")
        return
    if not args.port and not args.simulate:
        ap.error("give the gateway's COM port (see --list) or use --simulate")

    os.system("")  # enables ANSI escape codes in the Windows console
    out_dir = Path(__file__).parent / "data"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"link-{time.strftime('%H%M%S')}.csv"

    if args.simulate:
        source = simulate(args.duration, hz=5)
        closer = None
    else:
        import serial

        ser = serial.Serial(args.port, args.baud, timeout=1)
        source = (ser.readline().decode(errors="ignore") for _ in iter(int, 1))
        closer = ser.close

    nodes: dict[int, Node] = {}
    t0 = time.time()
    last_draw = 0.0
    try:
        with out_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_s", "n", "seq", "pir", "rad", "d", "sm", "x", "rssi"])
            for line in source:
                now = time.time()
                row = parse(line)
                if row:
                    nid = int(row["n"])
                    nodes.setdefault(nid, Node()).update(row, now)
                    w.writerow([round(now - t0, 3), nid, int(row["seq"]), int(row.get("pir", 0)), int(row.get("rad", 0)),
                                int(row.get("d", -1)), int(row.get("sm", -1)), int(row.get("x", 0)), int(row.get("rssi", 0))])
                if now - last_draw > 1.0:
                    last_draw = now
                    sys.stdout.write("\033[H\033[J" + render(nodes, now, t0) + "\n")
                    sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        if closer:
            closer()
    print("\n" + render(nodes, time.time(), t0))
    print(f"\nSaved packet log to {out_path}")


if __name__ == "__main__":
    main()
