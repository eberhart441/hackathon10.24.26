"""Configure flashed boards over serial, one command per board.

    rs-setup ports                         list serial ports (find your ESP32's COM number)
    rs-setup tx COM8 --id TX1              make the board a transmitter, remember its MAC
    rs-setup rx COM9 --id RX1 --tx TX1     make the board a receiver paired to TX1
    rs-setup info COM9                     print a board's saved settings

Relay mode (EXPERIMENTAL, needs the relay firmware from the feat/relay-experimental branch): only one
transmitter, the gateway, is cabled to the laptop; receivers send their lines to it over the air.

    rs-setup tx COM8 --id TX1                         the gateway transmitter (stays on USB)
    rs-setup rx COM9 --id RX1 --tx TX1 --relay-to TX1 each receiver; then it needs only power
    rs-setup gateway COM8 --id TX1                    last: tell the gateway which receivers to print

Transmitter MACs are remembered in boards.json next to this package, so `--tx TX1` works even
after TX1 is unplugged. Plug in one board at a time if you are unsure which COM port is which.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BOARDS_FILE = Path(__file__).resolve().parent.parent / "boards.json"
BOOT_WAIT_S = 2.5
MAX_RELAYS = 4  # receivers one gateway can print (firmware limit)


def _open(port: str, baud: int):
    import serial
    ser = serial.Serial(port, baud, timeout=0.2)
    time.sleep(BOOT_WAIT_S)  # opening the port can reset the board; let it boot
    ser.reset_input_buffer()
    return ser


def _command(ser, line: str, wait_s: float = 1.0) -> list[str]:
    """Send one console line and return the reply lines (OK/ERR/CFG/PONG) that arrive within wait_s."""
    ser.write((line + "\n").encode("ascii"))
    ser.flush()
    replies, end = [], time.monotonic() + wait_s
    while time.monotonic() < end:
        raw = ser.readline().decode("utf-8", errors="replace").strip()
        if raw.split(",", 1)[0] in ("OK", "ERR", "CFG", "PONG"):
            replies.append(raw)
    return replies


def _config(ser) -> dict[str, str]:
    cfg = {}
    for line in _command(ser, "GET"):
        if line.startswith("CFG,") and "=" in line:
            key, value = line[4:].split("=", 1)
            cfg[key] = value
    return cfg


def _load_boards() -> dict:
    try:
        return json.loads(BOARDS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_board(node_id: str, mac: str, role: str, **extra: str) -> None:
    boards = _load_boards()
    boards[node_id] = {"mac": mac, "role": role, **extra}
    BOARDS_FILE.write_text(json.dumps(boards, indent=2) + "\n", encoding="utf-8")


def _configure(port: str, baud: int, settings: dict[str, str]) -> dict[str, str]:
    with _open(port, baud) as ser:
        if not any(r.startswith("PONG") for r in _command(ser, "PING")):
            raise SystemExit(f"{port}: no reply to PING. Is the RoomSense firmware flashed, and is the "
                             "Arduino Serial Monitor (or rs-view) closed?")
        pairs = " ".join(f"{k}={v}" for k, v in settings.items())
        replies = _command(ser, f"SET {pairs}")
        errors = [r for r in replies if r.startswith("ERR")]
        if errors:
            hint = ""
            if any(k in settings for k in ("relay_to", "relays")) and any("unknown" in e or "key" in e for e in errors):
                hint = " This board has firmware without relay mode: flash the relay image first (feat/relay-experimental)."
            raise SystemExit(f"{port}: board rejected settings: {', '.join(errors)}.{hint}")
        cfg = _config(ser)
        _command(ser, "REBOOT", wait_s=0.3)
    return cfg


def cmd_ports(_args) -> int:
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports. Plug a board in with a data (not charge-only) USB cable.")
    for p in ports:
        hint = "  <- probably an ESP32" if any(s in (p.description or "") for s in ("CP210", "CH340", "CH910", "USB Serial", "UART")) else ""
        print(f"{p.device:8} {p.description}{hint}")
    return 0


def cmd_info(args) -> int:
    with _open(args.port, args.baud) as ser:
        cfg = _config(ser)
    if not cfg:
        print(f"{args.port}: no reply. Is the RoomSense firmware flashed?")
        return 1
    for k, v in cfg.items():
        print(f"{k:12} {v}")
    return 0


def cmd_tx(args) -> int:
    cfg = _configure(args.port, args.baud, {"node_id": args.id, "room_id": args.room, "role": "tx",
                                            "channel": str(args.channel)})
    mac = cfg.get("mac")
    if not mac:
        raise SystemExit(f"{args.port}: settings saved, but the board did not report its MAC")
    _save_board(args.id, mac, "tx")
    print(f"{args.id} on {args.port} is a transmitter, MAC {mac} (saved to {BOARDS_FILE.name}). Rebooting.")
    print(f"Next, for each receiver of {args.id}:  rs-setup rx COMx --id RX1 --tx {args.id}")
    return 0


def _tx_mac(name: str) -> str:
    known = _load_boards().get(name)
    if not known or known.get("role") != "tx":
        raise SystemExit(f"Unknown transmitter {name}. Run 'rs-setup tx' on it first, or pass a MAC.")
    return known["mac"]


def cmd_rx(args) -> int:
    mac = args.tx_mac or _tx_mac(args.tx)
    settings = {"node_id": args.id, "room_id": args.room, "role": "rx",
                "channel": str(args.channel), "paired_tx": mac.lower()}
    extra = {}
    if args.relay_to:
        settings["relay_to"] = _tx_mac(args.relay_to)
        extra["relay_to"] = args.relay_to
    cfg = _configure(args.port, args.baud, settings)
    _save_board(args.id, cfg.get("mac", "?"), "rx", **extra)
    print(f"{args.id} on {args.port} is a receiver paired to {args.tx or mac}. Rebooting.")
    if args.relay_to:
        print(f"It relays to {args.relay_to}: unplug it and power it from anything. "
              f"When all receivers are set up: rs-setup gateway COMx --id {args.relay_to}")
    return 0


def cmd_gateway(args) -> int:
    """Tell a transmitter which receivers' relayed lines to print (relay mode)."""
    boards = _load_boards()
    if boards.get(args.id, {}).get("role") != "tx":
        raise SystemExit(f"{args.id} is not a transmitter set up with rs-setup tx.")
    rx = sorted((name, b["mac"]) for name, b in boards.items()
                if b.get("role") == "rx" and b.get("relay_to") == args.id)
    if not rx:
        raise SystemExit(f"No receiver relays to {args.id} yet: rs-setup rx COMx --id RX1 --tx TX1 --relay-to {args.id}")
    if len(rx) > MAX_RELAYS:
        raise SystemExit(f"{len(rx)} receivers relay to {args.id}; the firmware takes at most {MAX_RELAYS}.")
    settings = {"relays": ",".join(mac for _, mac in rx), "pps": str(args.pps)}
    _configure(args.port, args.baud, settings)
    names = ", ".join(name for name, _ in rx)
    print(f"{args.id} on {args.port} now prints the data of {names}, and transmits {args.pps} packets/s. Rebooting.")
    print(f"Keep {args.id} plugged in and run:  rs-view --port {args.port}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--baud", type=int, default=921600)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports", help="list serial ports").set_defaults(fn=cmd_ports)
    info = sub.add_parser("info", help="print a board's settings")
    info.add_argument("port")
    info.set_defaults(fn=cmd_info)
    for name, fn in (("tx", cmd_tx), ("rx", cmd_rx)):
        s = sub.add_parser(name, help=f"configure a {'transmitter' if name == 'tx' else 'receiver'}")
        s.add_argument("port")
        s.add_argument("--id", required=True, help="node name, for example TX1 or RX1")
        s.add_argument("--room", default="ROOM1")
        s.add_argument("--channel", type=int, choices=(1, 6, 11), default=11, help="must match on every board")
        if name == "rx":
            g = s.add_mutually_exclusive_group(required=True)
            g.add_argument("--tx", help="node name of the transmitter set up earlier with 'rs-setup tx'")
            g.add_argument("--tx-mac", help="the transmitter's MAC, if it was not set up with rs-setup")
            s.add_argument("--relay-to", metavar="TX",
                           help="EXPERIMENTAL relay mode: send this receiver's data over the air to this gateway transmitter")
        s.set_defaults(fn=fn)
    gw = sub.add_parser("gateway", help="EXPERIMENTAL relay mode: tell a transmitter which receivers to print")
    gw.add_argument("port")
    gw.add_argument("--id", required=True, help="the gateway transmitter, for example TX1")
    gw.add_argument("--pps", type=int, default=50,
                    help="packets/s the gateway transmits; 50 keeps four relayed receivers within its USB speed")
    gw.set_defaults(fn=cmd_gateway)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
