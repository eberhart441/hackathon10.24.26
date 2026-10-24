"""A tiny local web page that shows the boards working, live.

    rs-view --port COM3                 (then it opens http://127.0.0.1:8765)
    rs-view --replay tests/fixtures/sample_capture.log     (no hardware needed)

It reads the receiver's serial port, parses the protocol lines, and shows for each receiver:
node health from its heartbeat, packet rate and loss, and a scrolling picture of the signal
(subcarrier up the side, time across, brighter = stronger). Walk between the boards and the
picture changes.

The MOTION / QUIET badge is a deliberately simple demo indicator (how much each subcarrier
wobbles over the last second, compared with a slowly learned baseline). It is NOT the
detection model, and "quiet" never means a room is empty.

Local only: it listens on 127.0.0.1, has no login, and stores nothing.
"""
from __future__ import annotations

import argparse
import json
import queue
import re
import statistics
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .activity import GainReference, normalize_gain
from .floorplan import DEFAULT_DIR as DEFAULT_PLAN_DIR, FloorPlan, tx_label
from .locate import Layout, Locator, link_score, load_layout
from .protocol import CsiRecord, Heartbeat, TagSummary, parse_line
from .sequence import SequenceTracker

DEFAULT_LAYOUT = Path(__file__).resolve().parent.parent / "layouts" / "demo-room.json"

WINDOW = 100          # packets (about one second) used for the activity measure
MIN_WINDOW = 30       # packets needed before we show an activity number
TICK_S = 0.1
OFFLINE_AFTER_S = 10.0
NO_SIGNAL_AFTER_S = 2.0
WEAK_RSSI_DBM = -85   # below this the link is too weak to judge
WEAK_MEAN_AMP = 4.0   # average subcarrier strength below this is basically no signal
WEAK_ACTIVITY = 0.2   # a real room never wobbles by exactly nothing; flat means blocked or dead
GLITCH_FRACTION = 0.4 # a packet whose overall strength is this far from typical is counted as a glitch
BASELINE_LEARN_BELOW = 1.3  # a window only teaches the quiet level if its activity is below 1.3x that level
BASELINE_FALL = 0.02        # per update toward a calmer level
BASELINE_RISE = 0.002       # per update toward a busier level: 10x slower
# A receiver is "obviously off" and left out of the location estimate when any of these hold.
OFF_MIN_RATE_SHARE = 0.4  # CSI lines/s below this share of the link's recent best rate (was 40 of about 100)
RATE_PEAK_DECAY = 0.9995  # per 0.1 s tick: the remembered best rate fades over a few minutes
RATE_BURST_SLACK = 1.2    # the remembered best never exceeds this times the board's own measured_pps
OFF_GLITCHES_10S = 15     # glitch packets in the last 10 s; healthy links show about 3
OFF_CLIPPED = 0.25        # share of subcarriers stuck at 255 (too close to the transmitter, or gain wrong)
# USB-serial chips found on ESP32 boards; Bluetooth serial ports are skipped
USB_SERIAL = re.compile(r"CP210|CH34|CH910|USB.?Serial|USB.?UART|JTAG", re.IGNORECASE)


class NodeView:
    """Everything the page shows for one receiver."""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.window: deque[tuple[float, ...]] = deque(maxlen=WINDOW)
        self.recent: deque[tuple[float, ...]] = deque(maxlen=5)
        self.gain_ref = GainReference()
        self.means: deque[float] = deque(maxlen=21)
        self.glitches = 0
        self.glitch_times: deque[float] = deque(maxlen=200)
        self.clipped = 0.0
        self.pending: list[list[int]] = []
        self.trackers: dict[str, SequenceTracker] = {}
        self.times: deque[float] = deque(maxlen=400)
        self.heartbeat: Heartbeat | None = None
        self.heartbeat_t: float | None = None
        self.rssi: int | None = None
        self.tx_mac: str | None = None
        self.baseline: float | None = None
        self.state = "warming"
        self.tags: dict[str, tuple[TagSummary, float]] = {}

    # --- feeding -------------------------------------------------------------
    def add_csi(self, rec: CsiRecord, now: float) -> None:
        # The receiver changes its gain on its own (the classic ESP32 does not report it), which
        # scales every subcarrier of a packet by the same factor, sometimes for one packet (~3x),
        # sometimes for good. Normalizing each packet to the link's fixed reference level cancels
        # that (see activity.py); a 5-packet median per subcarrier then removes other one-packet
        # spikes without hiding real, sustained motion.
        self.recent.append(normalize_gain(rec.amplitudes, self.gain_ref.update(rec.amplitudes)))
        self.window.append(tuple(statistics.median(col) for col in zip(*self.recent)))
        live = [a for a in rec.amplitudes if a]
        mean = statistics.mean(live) if live else 0.0
        if len(self.means) >= 11:
            typical = statistics.median(self.means)
            if typical > 0 and abs(mean - typical) > GLITCH_FRACTION * typical:
                self.glitches += 1
                self.glitch_times.append(now)
        self.means.append(mean)
        self.clipped = sum(1 for a in rec.amplitudes if a >= 255) / max(1, len(rec.amplitudes))
        self.pending.append(list(rec.amplitudes))
        if len(self.pending) > 600:
            del self.pending[:-600]
        self.trackers.setdefault(rec.tx_mac, SequenceTracker()).update(rec.seq)
        self.times.append(now)
        self.rssi = rec.rssi_dbm
        self.tx_mac = rec.tx_mac

    def add_heartbeat(self, hb: Heartbeat, now: float) -> None:
        self.heartbeat, self.heartbeat_t = hb, now

    def add_tag(self, summary: TagSummary, now: float) -> None:
        self.tags[summary.tag_id] = (summary, now)

    def reset_baseline(self) -> None:
        self.baseline = None

    # --- measuring -----------------------------------------------------------
    def activity(self) -> float | None:
        """Average, over subcarriers that carry signal, of how much each wobbled in the window."""
        if len(self.window) < MIN_WINDOW:
            return None
        spreads = []
        for column in zip(*self.window):
            if any(column):
                spreads.append(statistics.pstdev(column))
        return statistics.mean(spreads) if spreads else None

    def mean_amplitude(self) -> float | None:
        """Typical raw strength of recent packets over subcarriers that carry signal. Raw, not
        gain-normalized: a blocked or dead link must still look weak."""
        if not self.means:
            return None
        return statistics.median(list(self.means)[-5:])

    def update_state(self, now: float) -> tuple[float | None, float | None]:
        activity = self.activity()
        if not self.times or now - self.times[-1] > NO_SIGNAL_AFTER_S:
            self.state = "nosignal"
            return activity, None
        if activity is None:
            self.state = "warming"
            return None, None
        mean_amp = self.mean_amplitude()
        # A blocked or very weak link looks flat, which must never be read as a calm room.
        if (self.rssi is not None and self.rssi < WEAK_RSSI_DBM) or (mean_amp or 0) < WEAK_MEAN_AMP \
                or activity < WEAK_ACTIVITY:
            self.state = "weak"
            return activity, None
        if self.baseline is None:
            self.baseline = activity
        threshold = self.baseline * 1.8 + 0.4
        if activity > threshold:
            self.state = "motion"
        else:
            self.state = "quiet"
            # Learn only from clearly quiet windows, and rise much more slowly than fall. Otherwise the
            # pauses of someone moving on and off read as "quiet", the baseline creeps up, and within
            # a minute their motion becomes the normal level: a trapped person would fade out.
            if activity < BASELINE_LEARN_BELOW * self.baseline:
                rate = BASELINE_FALL if activity < self.baseline else BASELINE_RISE
                self.baseline += rate * (activity - self.baseline)
        return activity, threshold

    def off_reason(self, now: float, online: bool, rate: int) -> str | None:
        """Plain-language reason this receiver should not be trusted right now, or None if it looks fine.
        Called after update_state, so self.state is current."""
        if not online:
            return "offline: no heartbeat for 10 s" if self.heartbeat_t is not None else "no heartbeat yet"
        if self.state == "nosignal":
            return "no signal from its transmitter"
        if self.state == "weak":
            return "weak or blocked signal"
        if self.state == "warming":
            return "warming up"
        # Relative, not a fixed number: a relay gateway sends 50/s, a cabled link about 100/s. Expected is
        # what the board says it received (heartbeat) or this link's recent best, whichever is higher.
        # The fade follows the clock, not the number of calls (the PWA hub checks every 0.5 s, not 0.1 s).
        # Lines cannot really arrive faster than the board accepted them: a faster burst is a backlog
        # (a port just opened, or the laptop catching up after a stall), so the best is capped there.
        hb_pps = self.heartbeat.measured_pps if self.heartbeat else 0
        elapsed = max(0.0, now - getattr(self, "rate_peak_t", now))
        self.rate_peak_t = now
        peak = max(rate, getattr(self, "rate_peak", 0.0) * RATE_PEAK_DECAY ** (elapsed / TICK_S))
        self.rate_peak = min(peak, RATE_BURST_SLACK * hb_pps) if hb_pps else peak
        expected = max(self.rate_peak, hb_pps)
        if rate < OFF_MIN_RATE_SHARE * expected:
            return f"losing packets ({rate}/s)"
        recent = sum(1 for t in self.glitch_times if now - t <= 10.0)
        if recent > OFF_GLITCHES_10S:
            return f"glitching ({recent} bad packets in 10 s)"
        if self.clipped > OFF_CLIPPED:
            return "signal clipping (too close to the transmitter?)"
        return None

    def snapshot(self, now: float) -> dict:
        activity, threshold = self.update_state(now)
        columns, self.pending = self.pending, []
        hb_age = None if self.heartbeat_t is None else now - self.heartbeat_t
        hb = self.heartbeat
        lost = sum(t.lost for t in self.trackers.values())
        dup = sum(t.duplicates for t in self.trackers.values())
        rate = sum(1 for t in self.times if now - t <= 1.0)
        online = hb_age is not None and hb_age <= OFFLINE_AFTER_S
        off = self.off_reason(now, online, rate)
        return {
            "id": self.node_id,
            "offReason": off,
            "room": hb.room_id if hb else None,
            "txMac": self.tx_mac or (hb.paired_tx_mac if hb else None),
            "online": online,
            "hbAge": hb_age,
            "measuredPps": hb.measured_pps if hb else None,
            "freeHeap": hb.free_heap if hb else None,
            "drops": hb.csi_q_drops if hb else None,
            "mode": hb.rx_mode if hb else None,
            "fw": hb.fw_version if hb else None,
            "uptimeMs": hb.uptime_ms if hb else None,
            "rate": rate,
            "lost": lost,
            "dup": dup,
            "glitches": self.glitches,
            "rssi": self.rssi,
            "state": self.state,
            "activity": activity,
            "threshold": threshold,
            "columns": columns,
            "tags": [
                {"id": s.tag_id, "heard": s.packets_heard, "mean": s.mean_rssi, "max": s.max_rssi,
                 "age": round(now - t, 1)}
                for s, t in self.tags.values() if now - t <= 10
            ],
        }


class Hub:
    """Shared state: the nodes, the port errors, and the browsers listening."""

    def __init__(self, layout: Layout | None = None, plan: FloorPlan | None = None) -> None:
        """layout: fixed link positions. plan: positions edited on the page (used when layout is None)."""
        self.lock = threading.Lock()
        self.layout = layout
        self.plan = plan
        self.locator = Locator(layout) if layout else None
        self.located_layout = layout
        self.ports: set[str] = set()
        self.nodes: dict[str, NodeView] = {}
        self.errors: dict[str, str] = {}
        self.port_nodes: dict[str, set[str]] = {}
        self.clients: list["queue.Queue[str]"] = []
        self.clients_lock = threading.Lock()

    def feed_line(self, line: str, now: float | None = None, port: str | None = None) -> None:
        now = time.time() if now is None else now
        rec = parse_line(line)
        if rec is None:
            return
        with self.lock:
            if port is not None and hasattr(rec, "node_id"):
                self.port_nodes.setdefault(port, set()).add(rec.node_id)
            if isinstance(rec, CsiRecord):
                self._node(rec.node_id).add_csi(rec, now)
            elif isinstance(rec, Heartbeat):
                self._node(rec.node_id).add_heartbeat(rec, now)
            elif isinstance(rec, TagSummary):
                self._node(rec.node_id).add_tag(rec, now)

    def port_reset(self, port: str) -> None:
        """A port was (re)opened. Packets the board sent while we were not reading are not
        'lost' by the board, so forget the old sequence history for the nodes on that port."""
        with self.lock:
            for node_id in self.port_nodes.get(port, ()):
                node = self.nodes.get(node_id)
                if node is not None:
                    node.trackers.clear()
                    node.window.clear()
                    node.recent.clear()
                    node.means.clear()
                    node.gain_ref.reset()
                    node.times.clear()
                    node.pending.clear()

    def _node(self, node_id: str) -> NodeView:
        return self.nodes.setdefault(node_id, NodeView(node_id))

    def reset_baselines(self) -> None:
        with self.lock:
            for node in self.nodes.values():
                node.reset_baseline()

    def snapshot_json(self, now: float | None = None) -> str:
        now = time.time() if now is None else now
        with self.lock:
            nodes = [n.snapshot(now) for _, n in sorted(self.nodes.items())]
            errors = dict(self.errors)
            message = {"t": now, "nodes": nodes, "errors": errors, "ports": sorted(self.ports)}
            layout = self.layout
            if layout is None and self.plan is not None:
                layout = self.plan.layout({nid: n.tx_mac for nid, n in self.nodes.items()})
            if layout != self.located_layout:  # boards were moved: start a fresh estimate
                self.locator = Locator(layout) if layout else None
                self.located_layout = layout
            if self.plan is not None:
                message["plan"] = self.plan.to_json()
                message["transmitters"] = self._transmitters(now)
            if self.locator is not None:
                scores: dict[str, float | None] = {}
                excluded: dict[str, str] = {}
                for link in layout.links:
                    node = self.nodes.get(link.rx_id)
                    snap = next((n for n in nodes if n["id"] == link.rx_id), None)
                    if node is None or snap is None:
                        scores[link.rx_id] = None
                        excluded[link.rx_id] = "not connected"
                        continue
                    scores[link.rx_id] = link_score(snap["state"], snap["activity"], node.baseline, snap["threshold"])
                    if snap["offReason"]:
                        excluded[link.rx_id] = snap["offReason"]
                message["layout"] = layout.to_json()
                message["location"] = self.locator.update(scores, excluded)
        return json.dumps(message)

    def _transmitters(self, now: float) -> list[dict]:
        """Every transmitter we know of (named in boards.json or on the plan) or hear (through a receiver).
        A transmitter has no cable to the laptop, so 'heard by' is the only sign that it is alive."""
        names = self.plan.tx_names()
        heard: dict[str, list[dict]] = {}
        for nid, node in sorted(self.nodes.items()):
            if node.tx_mac:
                rate = sum(1 for t in node.times if now - t <= 1.0)
                heard.setdefault(node.tx_mac, []).append({"rx": nid, "rate": rate})
        macs = sorted(set(names) | set(heard), key=lambda m: names.get(m) or tx_label(m))
        return [{"id": names.get(m) or tx_label(m), "mac": m, "heardBy": heard.get(m, [])} for m in macs]

    # --- browsers ------------------------------------------------------------
    def subscribe(self) -> "queue.Queue[str]":
        q: "queue.Queue[str]" = queue.Queue(maxsize=50)
        with self.clients_lock:
            self.clients.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue[str]") -> None:
        with self.clients_lock:
            if q in self.clients:
                self.clients.remove(q)

    def broadcast(self, message: str) -> None:
        with self.clients_lock:
            clients = list(self.clients)
        for q in clients:
            try:
                q.put_nowait(message)
            except queue.Full:
                pass  # a slow browser just misses frames


def serial_reader(hub: Hub, port: str, baud: int, stop: threading.Event) -> None:
    """Read one port forever. If the port is busy or the board is unplugged, show the problem
    on the page and keep retrying, so replugging a board just works."""
    import serial  # imported here so the rest of the package works without pyserial

    while not stop.is_set():
        try:
            with serial.Serial(port, baud, timeout=0.2) as ser:
                with hub.lock:
                    hub.errors.pop(port, None)
                hub.port_reset(port)
                ser.reset_input_buffer()
                while not stop.is_set():
                    raw = ser.readline()
                    if raw:
                        hub.feed_line(raw.decode("utf-8", errors="replace"), port=port)
        except (serial.SerialException, OSError) as exc:
            with hub.lock:
                hub.errors[port] = str(exc)
            stop.wait(2.0)


def port_scanner(hub: Hub, baud: int, stop: threading.Event) -> None:
    """Start reading every ESP32 that is plugged in, now or later. Each receiver on USB shows up by itself."""
    from serial.tools import list_ports

    while not stop.is_set():
        for p in list_ports.comports():
            desc = p.description or ""
            if p.device in hub.ports or "bluetooth" in desc.lower() or not USB_SERIAL.search(desc):
                continue
            with hub.lock:
                hub.ports.add(p.device)
            threading.Thread(target=serial_reader, args=(hub, p.device, baud, stop), daemon=True).start()
        stop.wait(3.0)


def replay_reader(hub: Hub, path: Path, stop: threading.Event) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    while not stop.is_set():
        for line in lines:
            if stop.is_set():
                return
            hub.feed_line(line)
            time.sleep(0.01 if line.startswith("CSI,") else 0)


def ticker(hub: Hub, stop: threading.Event) -> None:
    while not stop.is_set():
        hub.broadcast(hub.snapshot_json())
        stop.wait(TICK_S)


def make_handler(hub: Hub):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # keep the console quiet
            pass

        def _send(self, code: int, body: bytes = b"", content_type: str = "text/plain; charset=utf-8") -> None:
            self.send_response(code)
            if body:
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path.split("?")[0] == "/plan/image":
                image = hub.plan.image() if hub.plan else None
                if image is None:
                    self.send_error(404)
                else:
                    self._send(200, image[0], image[1])
            elif self.path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                q = hub.subscribe()
                try:
                    while True:
                        try:
                            message = q.get(timeout=15)
                            self.wfile.write(f"data: {message}\n\n".encode("utf-8"))
                        except queue.Empty:
                            self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    hub.unsubscribe(q)
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            # Only this page may change things: a web page from elsewhere could otherwise post to localhost.
            port = self.server.server_address[1]
            origin = self.headers.get("Origin")
            if origin is not None and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
                self._send(403, b"forbidden")
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > 16 * 1024 * 1024:
                self._send(413, b"too large")
                return
            body = self.rfile.read(length)
            try:
                if self.path == "/reset":
                    hub.reset_baselines()
                elif hub.plan is None or not self.path.startswith("/plan/"):
                    self.send_error(404)
                    return
                elif self.path == "/plan/image":
                    content_type = self.headers.get("Content-Type", "")
                    if "dxf" in content_type.lower():
                        hub.plan.set_dxf(body)
                    else:
                        hub.plan.set_image(body, content_type)
                else:
                    data = json.loads(body or b"{}")
                    if self.path == "/plan/scale":
                        hub.plan.set_scale(float(data["width_px"]), float(data["height_px"]), float(data["ft_per_px"]),
                                           bool(data.get("confirmed", True)))
                    elif self.path == "/plan/size":
                        hub.plan.set_size(float(data["width_ft"]), float(data["height_ft"]))
                    elif self.path == "/plan/board":
                        hub.plan.place(str(data["id"]), str(data["role"]), float(data["x"]), float(data["y"]),
                                       data.get("mac"))
                    elif self.path == "/plan/board/remove":
                        hub.plan.remove(str(data["id"]))
                    else:
                        self.send_error(404)
                        return
            except (ValueError, KeyError, TypeError) as exc:
                self._send(400, str(exc).encode("utf-8"))
                return
            self._send(204)

    return Handler


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", action="append", default=[],
                   help="receiver serial port (repeat for several). Default: every ESP32 plugged in, found automatically")
    p.add_argument("--baud", type=int, default=921600)
    p.add_argument("--replay", type=Path, help="play back a captured log instead of reading hardware")
    p.add_argument("--layout", type=Path,
                   help="fixed link positions (JSON), instead of placing boards on the page")
    p.add_argument("--plan-dir", type=Path, default=DEFAULT_PLAN_DIR,
                   help="where the floor plan picture and board positions are saved (default firmware/tools/site)")
    p.add_argument("--simulate", action="store_true",
                   help="fake receivers with a virtual walker (positions from --layout, default layouts/demo-room.json)")
    p.add_argument("--http-port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args(argv)

    plan = None
    if args.simulate:
        layout = load_layout(args.layout or DEFAULT_LAYOUT)
        from .simulate import seed_plan
        plan = FloorPlan(folder=None, boards_file=None)  # the simulator's boards live in memory only
        seed_plan(layout, plan)
        hub = Hub(plan=plan)
    elif args.layout:
        layout = load_layout(args.layout)
        hub = Hub(layout)
    else:
        layout = None
        plan = FloorPlan(args.plan_dir)
        hub = Hub(plan=plan)

    stop = threading.Event()
    threads = [threading.Thread(target=ticker, args=(hub, stop), daemon=True)]
    for port in args.port:
        hub.ports.add(port)
        threads.append(threading.Thread(target=serial_reader, args=(hub, port, args.baud, stop), daemon=True))
    if not args.port and not args.replay and not args.simulate:
        threads.append(threading.Thread(target=port_scanner, args=(hub, args.baud, stop), daemon=True))
    if args.replay:
        threads.append(threading.Thread(target=replay_reader, args=(hub, args.replay, stop), daemon=True))
    if args.simulate:
        from .simulate import run as simulate
        threads.append(threading.Thread(target=simulate, args=(layout, hub.feed_line, stop), daemon=True))
    for t in threads:
        t.start()

    server = ThreadingHTTPServer(("127.0.0.1", args.http_port), make_handler(hub))
    url = f"http://127.0.0.1:{args.http_port}"
    print(f"Beacon live view at {url}  (Ctrl+C to stop)")
    if plan is not None and plan.folder is not None:
        print(f"Floor plan and board positions are saved in {plan.folder}")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
    return 0


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Beacon live view</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: dark; }
  body { margin: 0; padding: 20px; background: #0f1419; color: #e6edf3; font: 15px/1.4 system-ui, sans-serif; }
  h1 { margin: 0 0 4px; font-size: 22px; }
  .note { color: #9fb0c0; max-width: 900px; margin: 0 0 18px; }
  .card { background: #161d26; border: 1px solid #2a3644; border-radius: 10px; padding: 14px 16px; margin-bottom: 18px; max-width: 980px; }
  .head { display: flex; flex-wrap: wrap; gap: 10px 16px; align-items: center; margin-bottom: 10px; }
  .title { font-size: 18px; font-weight: 600; }
  .sub { color: #9fb0c0; }
  .pill { padding: 2px 10px; border-radius: 999px; font-weight: 600; font-size: 13px; }
  .ok { background: #123d27; color: #5be49b; } .bad { background: #4a1a1a; color: #ff8a80; }
  .badge { padding: 4px 14px; border-radius: 8px; font-weight: 700; letter-spacing: .5px; }
  .b-motion { background: #ff9f1c; color: #1a1200; } .b-quiet { background: #1f4d36; color: #9ff0c4; }
  .b-warming { background: #2a3644; color: #cdd9e5; } .b-nosignal { background: #4a1a1a; color: #ff8a80; }
  .b-weak { background: #5c3a00; color: #ffd28a; }
  .stats { display: flex; flex-wrap: wrap; gap: 6px 22px; margin: 6px 0 12px; }
  .stat b { display: block; font-size: 20px; } .stat span { color: #9fb0c0; font-size: 12px; }
  canvas { width: 100%; max-width: 940px; border-radius: 6px; background: #0b0f14; display: block; }
  .label { color: #9fb0c0; font-size: 12px; margin: 10px 0 4px; }
  button { background: #2a3644; color: #e6edf3; border: 0; border-radius: 6px; padding: 6px 12px; cursor: pointer; }
  button:hover { background: #3a4a5c; }
  #errors { color: #ff8a80; margin-bottom: 12px; }
  #waiting { color: #9fb0c0; }
  .card.wide { max-width: 1240px; }
  .tools { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; margin-bottom: 10px; }
  .btn { background: #2a3644; color: #e6edf3; border-radius: 6px; padding: 6px 12px; cursor: pointer; }
  .btn:hover { background: #3a4a5c; }
  button.active { background: #ff9f1c; color: #1a1200; }
  .hint { color: #ffd28a; }
  .planwrap { display: flex; flex-wrap: wrap; gap: 14px; align-items: flex-start; }
  #locate { flex: 1 1 560px; max-width: 900px; touch-action: none; cursor: crosshair; }
  .side { flex: 1 1 260px; max-width: 340px; }
  .brow { display: flex; gap: 8px; align-items: center; padding: 7px 0; border-bottom: 1px solid #2a3644; }
  .brow .who { flex: 1; min-width: 0; }
  .brow .who b { display: block; }
  .brow .who span { color: #9fb0c0; font-size: 12px; }
  .dot { width: 12px; height: 12px; border-radius: 50%; flex: none; }
  .sq { width: 12px; height: 12px; background: #e6edf3; flex: none; }
  .brow button { padding: 4px 10px; }
</style>
</head>
<body>
<h1>Beacon live view</h1>
<p class="note">Raw signal from the receiver, for checking the boards. The badge is a simple demo indicator,
not the detection model, and &ldquo;quiet&rdquo; never means a room is empty. Walk between the two boards and watch the picture change.</p>
<div id="errors"></div>
<div id="waiting">Waiting for data from the receiver&hellip;</div>
<div class="card wide" id="where" style="display:none">
  <div class="head"><div class="title">Floor plan</div><span class="badge" id="where-badge"></span><span class="sub" id="where-text"></span></div>
  <div class="tools" id="plan-tools">
    <label class="btn">Upload floor plan<input type="file" id="plan-file" accept=".dxf,image/png,image/jpeg,image/webp,image/gif" hidden></label>
    <button id="scale-btn">Set scale</button>
    <button id="zoom-btn">Show whole plan</button>
    <button id="truth-btn" title="While walking, click where you really are; the app compares its estimate">Accuracy test</button>
    <span class="sub" id="truth-stats"></span>
    <span class="hint" id="plan-hint"></span>
  </div>
  <div class="planwrap">
    <canvas id="locate" width="900" height="600"></canvas>
    <div class="side" id="plan-side">
      <div class="label">Every board. <b>Place</b>, then click the plan where the board stands. Drag a board on the plan to move it.</div>
      <div id="board-list"></div>
    </div>
  </div>
  <div class="label">Where the motion is, estimated from which links (TX&ndash;RX lines) are disturbed: a zone about 1 to 2 m across, for one moving person, only
  between placed boards. Orange = likely area, white dot = estimate (ring = uncertainty), faded dots = recent path. Someone who stops moving drops off the map;
  that never means they left.</div>
</div>
<div class="card" id="overview">
  <div class="title">Room overview</div>
  <div class="label" id="room-label">Schematic of the demo room (13 ft x 9 ft 4 in) with the planned node layout. Each line is a radio link from the
  transmitter (TX) to a receiver; its colour is what that link sees. If your boards are placed differently, edit LAYOUT in this page's script.</div>
  <canvas id="room" width="800" height="290"></canvas>
  <div class="label">Activity on every link, last 30 seconds (a walker should disturb one link and then the other).</div>
  <canvas id="timeline" width="800" height="120"></canvas>
</div>
<div id="nodes"></div>
<script>
const W = 800, ROWS = 64, ROW_PX = 3, H = ROWS * ROW_PX, AH = 90, HISTORY = 300;
const cards = {};
const STATE_LABEL = {motion: 'MOTION', quiet: 'QUIET', warming: 'WARMING UP', weak: 'WEAK SIGNAL', nosignal: 'NO SIGNAL'};
const STATE_COLOUR = {motion: '#ff9f1c', quiet: '#3ddc84', warming: '#6b7c8f', weak: '#ff6b6b', nosignal: '#ff6b6b'};
const LINE_COLOURS = ['#5be49b', '#6cb6ff', '#e3a8ff', '#ffd166'];
// Planned layout, in feet from the top-left corner of the room (x along the 13 ft side, y along the 9 ft 4 in side).
// The door is in the top-left corner of the left (short) wall. TX is on the bottom wall; the first receiver is across
// the entry strip (the doorway link); the second is near the far end (the interior link).
const LAYOUT = {room: [13, 9.33], tx: [2, 9.33], rx: [[2, 0], [12.5, 1.5]], door: [0, 3]};
const STOPS = [[13,8,135],[84,2,163],[139,10,165],[185,50,137],[219,92,104],[244,136,73],[254,188,43],[240,249,33]];
function colour(t) {
  t = Math.max(0, Math.min(1, t)) * (STOPS.length - 1);
  const i = Math.min(STOPS.length - 2, Math.floor(t)), f = t - i, a = STOPS[i], b = STOPS[i + 1];
  return `rgb(${Math.round(a[0] + (b[0]-a[0])*f)},${Math.round(a[1] + (b[1]-a[1])*f)},${Math.round(a[2] + (b[2]-a[2])*f)})`;
}
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
function stat(label) { const d = el('div', 'stat'); const v = el('b', null, '-'); d.append(v, el('span', null, label)); return {d, v}; }

function makeCard(id) {
  const root = el('div', 'card');
  const head = el('div', 'head');
  const title = el('div', 'title', id), sub = el('div', 'sub'), pill = el('span', 'pill'), badge = el('span', 'badge');
  const reset = el('button', null, 'Reset baseline');
  reset.onclick = () => fetch('/reset', {method: 'POST'});
  head.append(title, pill, badge, sub, reset);
  const stats = el('div', 'stats');
  const s = {};
  for (const [k, label] of [['rate','CSI lines / s'],['pps','measured pps (board)'],['lost','packets lost'],['dup','repeats'],['glitch','glitch packets'],['rssi','RSSI dBm'],['act','activity'],['heap','free heap'],['drops','queue drops'],['up','uptime']]) {
    s[k] = stat(label); stats.append(s[k].d);
  }
  const l1 = el('div', 'label', 'Signal strength per subcarrier (up the side) over time (newest on the right). Brighter = stronger.');
  const heat = el('canvas'); heat.width = W; heat.height = H;
  const l2 = el('div', 'label', 'Activity (how much the signal wobbles). Dashed line = learned threshold.');
  const act = el('canvas'); act.width = W; act.height = AH;
  const tags = el('div', 'sub');
  root.append(head, stats, l1, heat, l2, act, tags);
  document.getElementById('nodes').append(root);
  return {root, title, sub, pill, badge, s, heat, hctx: heat.getContext('2d'), act, actx: act.getContext('2d'), tags, scale: 40, hist: []};
}

function fmt(v, d) { return (v === null || v === undefined) ? '-' : (d !== undefined ? Number(v).toFixed(d) : v); }

function update(n) {
  const c = cards[n.id] || (cards[n.id] = makeCard(n.id));
  c.title.textContent = n.id + (n.room ? '  \u00b7  room ' + n.room : '');
  c.sub.textContent = n.txMac ? 'listening to ' + n.txMac : '';
  c.pill.textContent = n.online ? 'ONLINE' : (n.hbAge === null ? 'NO HEARTBEAT YET' : 'OFFLINE');
  c.pill.className = 'pill ' + (n.online ? 'ok' : 'bad');
  const labels = STATE_LABEL;
  c.badge.textContent = labels[n.state] || n.state;
  c.badge.className = 'badge b-' + n.state;
  c.s.rate.v.textContent = fmt(n.rate); c.s.pps.v.textContent = fmt(n.measuredPps);
  c.s.lost.v.textContent = fmt(n.lost); c.s.dup.v.textContent = fmt(n.dup);
  c.s.glitch.v.textContent = fmt(n.glitches);
  c.s.rssi.v.textContent = fmt(n.rssi); c.s.act.v.textContent = fmt(n.activity, 2);
  c.s.heap.v.textContent = n.freeHeap === null ? '-' : Math.round(n.freeHeap / 1024) + ' KB';
  c.s.drops.v.textContent = fmt(n.drops);
  c.s.up.v.textContent = n.uptimeMs === null ? '-' : Math.round(n.uptimeMs / 1000) + ' s';

  // heatmap: scroll left, draw the new columns on the right edge
  const cols = n.columns.slice(-W);
  if (cols.length) {
    c.hctx.drawImage(c.heat, -cols.length, 0);
    let peak = 1;
    for (const col of cols) for (const a of col) if (a > peak) peak = a;
    c.scale = Math.max(20, 0.97 * c.scale + 0.03 * peak);
    cols.forEach((col, i) => {
      const x = W - cols.length + i;
      for (let r = 0; r < col.length && r < ROWS; r++) {
        c.hctx.fillStyle = colour(col[r] / c.scale);
        c.hctx.fillRect(x, H - (r + 1) * ROW_PX, 1, ROW_PX);
      }
    });
  }

  // activity line
  c.hist.push({a: n.activity, t: n.threshold}); if (c.hist.length > HISTORY) c.hist.shift();
  const x = c.actx; x.clearRect(0, 0, W, AH);
  const top = Math.max(1, ...c.hist.map(p => Math.max(p.a || 0, p.t || 0))) * 1.15;
  const px = i => (i / (HISTORY - 1)) * W, py = v => AH - (v / top) * (AH - 6) - 3;
  x.strokeStyle = '#5be49b'; x.lineWidth = 2; x.beginPath(); let started = false;
  c.hist.forEach((p, i) => { if (p.a === null) return; if (!started) { x.moveTo(px(i), py(p.a)); started = true; } else x.lineTo(px(i), py(p.a)); });
  x.stroke();
  x.strokeStyle = '#ff9f1c'; x.setLineDash([6, 5]); x.lineWidth = 1; x.beginPath(); started = false;
  c.hist.forEach((p, i) => { if (p.t === null) return; if (!started) { x.moveTo(px(i), py(p.t)); started = true; } else x.lineTo(px(i), py(p.t)); });
  x.stroke(); x.setLineDash([]);

  c.tags.textContent = n.tags.length ? 'Tags heard: ' + n.tags.map(t => `${t.id} (${t.heard}/s, mean ${t.mean} dBm)`).join(', ') : '';
}

function drawRoom(nodes) {
  const cv = document.getElementById('room'), g = cv.getContext('2d');
  const S = 27, X0 = (cv.width - LAYOUT.room[0] * S) / 2, Y0 = 18;
  const P = p => [X0 + p[0] * S, Y0 + p[1] * S];
  g.clearRect(0, 0, cv.width, cv.height);
  g.strokeStyle = '#4b5d70'; g.lineWidth = 3; g.strokeRect(X0, Y0, LAYOUT.room[0] * S, LAYOUT.room[1] * S);
  const d0 = P([0, LAYOUT.door[0]]), d1 = P([0, LAYOUT.door[1]]);
  g.strokeStyle = '#0b0f14'; g.lineWidth = 6; g.beginPath(); g.moveTo(d0[0], d0[1] + 2); g.lineTo(d1[0], d1[1] - 2); g.stroke();
  g.strokeStyle = '#6cb6ff'; g.lineWidth = 2; g.setLineDash([4, 4]); g.beginPath(); g.moveTo(d0[0], d0[1]); g.lineTo(d1[0], d1[1]); g.stroke(); g.setLineDash([]);
  g.fillStyle = '#6cb6ff'; g.font = '12px system-ui'; g.fillText('door', d0[0] - 34, (d0[1] + d1[1]) / 2 + 4);
  const tx = P(LAYOUT.tx);
  nodes.forEach((n, i) => {
    const pos = LAYOUT.rx[i]; if (!pos) return;
    const rx = P(pos), col = STATE_COLOUR[n.state] || '#6b7c8f';
    g.strokeStyle = col; g.lineWidth = n.state === 'motion' ? 7 : 3;
    g.setLineDash(n.state === 'weak' || n.state === 'nosignal' ? [8, 6] : []);
    g.beginPath(); g.moveTo(tx[0], tx[1]); g.lineTo(rx[0], rx[1]); g.stroke(); g.setLineDash([]);
    g.fillStyle = col; g.beginPath(); g.arc(rx[0], rx[1], 9, 0, 7); g.fill();
    g.fillStyle = '#e6edf3'; g.font = '13px system-ui'; g.fillText(n.id, rx[0] + 12, rx[1] + 4);
    g.fillStyle = col; g.fillText(STATE_LABEL[n.state] || n.state, (tx[0] + rx[0]) / 2 + 8, (tx[1] + rx[1]) / 2 - 6);
  });
  g.fillStyle = '#e6edf3'; g.fillRect(tx[0] - 8, tx[1] - 8, 16, 16);
  g.font = '13px system-ui'; g.fillText('TX', tx[0] + 12, tx[1] + 5);
}

function drawTimeline(nodes) {
  const cv = document.getElementById('timeline'), g = cv.getContext('2d');
  g.clearRect(0, 0, cv.width, cv.height);
  let top = 1;
  nodes.forEach(n => { const c = cards[n.id]; if (c) for (const p of c.hist) if (p.a && p.a > top) top = p.a; });
  top *= 1.15;
  nodes.forEach((n, k) => {
    const c = cards[n.id]; if (!c) return;
    g.strokeStyle = LINE_COLOURS[k % LINE_COLOURS.length]; g.lineWidth = 2; g.beginPath(); let on = false;
    c.hist.forEach((p, i) => {
      if (p.a === null) return;
      const x = (i / (HISTORY - 1)) * cv.width, y = cv.height - 6 - (p.a / top) * (cv.height - 14);
      if (!on) { g.moveTo(x, y); on = true; } else g.lineTo(x, y);
    });
    g.stroke();
    g.fillStyle = g.strokeStyle; g.font = '12px system-ui'; g.fillText(n.id, 8 + k * 60, 14);
  });
}

function drawLocation(layout, loc, nodes) {
  const cv = document.getElementById('locate'), g = cv.getContext('2d');
  const [rw, rh] = layout.room, pad = 30;
  // View: the room plus every board (some may stand outside it, e.g. in a hallway), with a margin.
  let minX = 0, minY = 0, maxX = rw, maxY = rh;
  layout.links.forEach(l => [l.tx, l.rx].forEach(p => {
    minX = Math.min(minX, p[0]); minY = Math.min(minY, p[1]); maxX = Math.max(maxX, p[0]); maxY = Math.max(maxY, p[1]);
  }));
  minX -= 1.5; minY -= 1.5; maxX += 1.5; maxY += 1.5;
  const S = Math.min((cv.width - 2 * pad) / (maxX - minX), (cv.height - 2 * pad) / (maxY - minY));
  const X0 = (cv.width - (maxX - minX) * S) / 2 - minX * S, Y0 = (cv.height - (maxY - minY) * S) / 2 - minY * S;
  const P = p => [X0 + p[0] * S, Y0 + p[1] * S];
  g.clearRect(0, 0, cv.width, cv.height);
  // floor-plan walls (from the DXF), clipped to the view
  if (layout.walls && layout.walls.length) {
    g.save(); g.beginPath(); g.rect(X0 + minX * S, Y0 + minY * S, (maxX - minX) * S, (maxY - minY) * S); g.clip();
    g.strokeStyle = '#3a4757'; g.lineWidth = 2;
    layout.walls.forEach(line => {
      g.beginPath(); line.forEach((p, i) => { const q = P(p); i ? g.lineTo(q[0], q[1]) : g.moveTo(q[0], q[1]); }); g.stroke();
    });
    g.restore();
  }
  g.fillStyle = '#0b0f14'; g.fillRect(X0, Y0, rw * S, rh * S);
  // likelihood grid, only while something is moving
  if (loc.moving) {
    const {cols, rows, cells} = loc.grid, cw = rw * S / cols, ch = rh * S / rows;
    cells.forEach((v, i) => {
      if (v < 0.15) return;
      g.fillStyle = `rgba(255,159,28,${(v * 0.75).toFixed(2)})`;
      g.fillRect(X0 + (i % cols) * cw, Y0 + Math.floor(i / cols) * ch, cw + 0.5, ch + 0.5);
    });
  }
  g.strokeStyle = '#4b5d70'; g.lineWidth = 3; g.strokeRect(X0, Y0, rw * S, rh * S);
  // areas no working link can see: shaded as unknown
  if (loc.grid && loc.grid.covered) {
    const {cols, rows, covered} = loc.grid, cw = rw * S / cols, ch = rh * S / rows;
    g.fillStyle = 'rgba(140,150,165,0.22)';
    covered.forEach((ok, i) => { if (!ok) g.fillRect(X0 + (i % cols) * cw, Y0 + Math.floor(i / cols) * ch, cw + 0.5, ch + 0.5); });
  }
  // grid lines every foot
  g.strokeStyle = 'rgba(75,93,112,0.25)'; g.lineWidth = 1;
  for (let f = 1; f < rw; f++) { g.beginPath(); g.moveTo(X0 + f * S, Y0); g.lineTo(X0 + f * S, Y0 + rh * S); g.stroke(); }
  for (let f = 1; f < rh; f++) { g.beginPath(); g.moveTo(X0, Y0 + f * S); g.lineTo(X0 + rw * S, Y0 + f * S); g.stroke(); }
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
  const txs = {};
  layout.links.forEach(l => {
    const n = byId[l.rx_id], state = n ? n.state : 'nosignal';
    const off = loc.excluded ? loc.excluded[l.rx_id] : null;
    const col = off ? '#6b7c8f' : (STATE_COLOUR[state] || '#6b7c8f');
    const a = P(l.tx), b = P(l.rx);
    g.strokeStyle = col; g.lineWidth = !off && state === 'motion' ? 5 : 2;
    g.setLineDash(off || state === 'weak' || state === 'nosignal' || state === 'warming' ? [8, 6] : []);
    g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke(); g.setLineDash([]);
    // a receiver standing right next to its transmitter has no line to draw: show a ring instead
    const sameSpot = Math.hypot(a[0] - b[0], a[1] - b[1]) < 4;
    if (sameSpot) { g.lineWidth = state === 'motion' ? 5 : 2; g.beginPath(); g.arc(b[0], b[1], 18, 0, 7); g.stroke(); }
    g.fillStyle = col; g.beginPath(); g.arc(b[0], b[1], 9, 0, 7); g.fill();
    g.fillStyle = '#e6edf3'; g.font = '13px system-ui';
    const s = loc.scores[l.rx_id];
    g.fillText(l.rx_id + (n ? '' : ' (not seen)') + (s === null || s === undefined ? '' : '  ' + s.toFixed(1)), b[0] + 12, b[1] - (sameSpot ? 22 : 10));
    if (off) { g.fillStyle = '#ffb4a8'; g.font = '12px system-ui'; g.fillText('left out: ' + off, b[0] + 12, b[1] + (sameSpot ? 30 : 8)); }
    txs[l.tx.join(',')] = a;
  });
  Object.values(txs).forEach((a, i) => {
    g.fillStyle = '#e6edf3'; g.fillRect(a[0] - 8, a[1] - 8, 16, 16);
    g.font = '13px system-ui'; g.fillText('TX', a[0] + 12, a[1] + 18);
  });
  loc.trail.forEach((p, i) => {
    const q = P(p); g.fillStyle = `rgba(108,182,255,${(0.1 + 0.6 * i / loc.trail.length).toFixed(2)})`;
    g.beginPath(); g.arc(q[0], q[1], 4, 0, 7); g.fill();
  });
  const badge = document.getElementById('where-badge'), text = document.getElementById('where-text');
  const note = loc.note ? '  ' + loc.note : '';
  if (loc.moving) {
    const q = P([loc.x, loc.y]);
    g.strokeStyle = 'rgba(255,255,255,0.7)'; g.lineWidth = 2; g.beginPath(); g.arc(q[0], q[1], loc.spread * S, 0, 7); g.stroke();
    g.fillStyle = '#ffffff'; g.beginPath(); g.arc(q[0], q[1], 9, 0, 7); g.fill();
    badge.textContent = loc.degraded ? 'MOTION (LESS SURE)' : 'MOTION'; badge.className = 'badge b-motion';
    text.textContent = `near x ${loc.x.toFixed(1)} ft, y ${loc.y.toFixed(1)} ft (±${loc.spread.toFixed(1)} ft)` + note;
  } else if (loc.motion_seen) {
    badge.textContent = 'MOTION (CANNOT PLACE)'; badge.className = 'badge b-motion';
    text.textContent = (loc.note || 'Motion seen, but not enough working links to place it.');
  } else {
    if (loc.last) {
      const q = P(loc.last); g.strokeStyle = '#9fb0c0'; g.lineWidth = 2; g.setLineDash([3, 3]);
      g.beginPath(); g.arc(q[0], q[1], 9, 0, 7); g.stroke(); g.setLineDash([]);
    }
    badge.textContent = 'NO MOTION'; badge.className = 'badge b-quiet';
    text.textContent = loc.last ? 'dashed ring = last place motion was seen. Not moving ≠ not there.' : 'no motion seen yet';
  }
}

// ---- floor plan: picture, scale, board placement, motion estimate ----
const cvL = document.getElementById('locate'), gL = cvL.getContext('2d');
let PLAN = null, PLAN_V = -1, IMG = null, MODE = null, DRAG = null, LAST = null;
const PAD = 24;  // margin so boards on the outer walls and their names stay visible
const rows = {};

function post(path, data, raw) {
  const type = raw && (/\.dxf$/i.test(raw.name || '') ? 'application/dxf' : raw.type || 'application/octet-stream');
  const opts = raw ? {method: 'POST', headers: {'Content-Type': type}, body: raw}
                   : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)};
  return fetch(path, opts).then(r => { if (!r.ok) r.text().then(t => alert('Not saved: ' + t)); return r; });
}
function dims() { return [PLAN.plan.width_ft, PLAN.plan.height_ft]; }
// The part of the plan on screen: the whole plan, or (zoomed) the placed boards plus a margin.
let ZOOM = true, VIEW = {x0: 0, y0: 0, w: 13, h: 9.33};
function fitView() {
  const [w, h] = dims(), ids = Object.keys(PLAN.boards);
  if (!ZOOM || ids.length < 2) VIEW = {x0: 0, y0: 0, w, h};
  else {
    const xs = ids.map(id => PLAN.boards[id].x), ys = ids.map(id => PLAN.boards[id].y), m = 5;
    const x0 = Math.max(0, Math.min(...xs) - m), y0 = Math.max(0, Math.min(...ys) - m);
    const x1 = Math.min(w, Math.max(...xs) + m), y1 = Math.min(h, Math.max(...ys) + m);
    VIEW = {x0, y0, w: Math.max(x1 - x0, 8), h: Math.max(y1 - y0, 6)};
  }
  cvL.height = Math.max(200, Math.min(1400, Math.round((cvL.width - 2 * PAD) * VIEW.h / VIEW.w) + 2 * PAD));
  document.getElementById('zoom-btn').textContent = ZOOM ? 'Show whole plan' : 'Zoom to boards';
}
function scale() { return (cvL.width - 2 * PAD) / VIEW.w; }
function toFt(ev) {
  const r = cvL.getBoundingClientRect(), s = scale();
  return [VIEW.x0 + ((ev.clientX - r.left) * (cvL.width / r.width) - PAD) / s,
          VIEW.y0 + ((ev.clientY - r.top) * (cvL.height / r.height) - PAD) / s];
}
function toPx(p) { const s = scale(); return [PAD + (p[0] - VIEW.x0) * s, PAD + (p[1] - VIEW.y0) * s]; }
function boardPos(id) {
  if (DRAG && DRAG.id === id) return DRAG.pos;
  const b = PLAN.boards[id]; return b ? [b.x, b.y] : null;
}
function hint(text) { document.getElementById('plan-hint').textContent = text || ''; }

function setPlan(plan) {
  PLAN = plan;
  if (plan.version === PLAN_V) return;
  PLAN_V = plan.version;
  fitView();
  document.getElementById('scale-btn').textContent = plan.plan.image ? 'Set scale' : 'Set area size';
  if (plan.plan.image) {
    const img = new Image();
    img.onload = () => {
      IMG = img;
      if (!PLAN.plan.width_px)  // fresh upload: placeholder scale until the user measures one
        post('/plan/scale', {width_px: img.naturalWidth, height_px: img.naturalHeight, ft_per_px: 0.05, confirmed: false});
      drawPlan();
    };
    img.src = '/plan/image?v=' + plan.version;
  } else IMG = null;
  if (plan.plan.image && !plan.plan.scaled) hint('Set the scale: click "Set scale", then two points a known distance apart.');
  else if (!MODE) hint('');
}

document.getElementById('plan-file').onchange = ev => {
  const f = ev.target.files[0]; if (f) post('/plan/image', null, f); ev.target.value = '';
};
document.getElementById('scale-btn').onclick = () => {
  if (!PLAN) return;
  if (!PLAN.plan.image) {
    const a = prompt('Size of the area in feet, width x height (for example 13 x 9.3). Add m for metres (4 x 2.8 m).');
    const m = a && a.match(/([\d.]+)\s*[x×]\s*([\d.]+)\s*(m)?/i);
    if (m) { const k = m[3] ? 3.28084 : 1; post('/plan/size', {width_ft: +m[1] * k, height_ft: +m[2] * k}); }
    return;
  }
  if (!IMG) return;
  MODE = {kind: 'scale', pts: []}; hint('Click the first end of a distance you know (a wall, a door). Esc cancels.');
};

function placeBoard(id, role, mac) {
  MODE = {kind: 'place', id, role, mac}; hint('Click on the plan where ' + id + ' stands. Esc cancels.');
}
function removeBoard(id) { post('/plan/board/remove', {id}); }

cvL.addEventListener('pointerdown', ev => {
  if (!PLAN) return;
  const p = toFt(ev);
  if (TRUTH.on) { markTruth(p); return; }
  if (MODE && MODE.kind === 'place') {
    post('/plan/board', {id: MODE.id, role: MODE.role, mac: MODE.mac, x: p[0], y: p[1]}); MODE = null; hint(''); return;
  }
  if (MODE && MODE.kind === 'scale') {
    MODE.pts.push(p);
    if (MODE.pts.length === 1) { hint('Now click the other end.'); drawPlan(); return; }
    const [a, b] = MODE.pts, imgPx = Math.hypot(b[0] - a[0], b[1] - a[1]) * IMG.naturalWidth / dims()[0];
    const ans = prompt('Real distance between the two points? For example 13 ft or 4.2 m');
    const m = ans && ans.match(/([\d.]+)\s*(m|ft)?/i);
    MODE = null; hint('');
    if (m && imgPx > 3) {
      const ft = +m[1] * ((m[2] || 'ft').toLowerCase() === 'm' ? 3.28084 : 1);
      post('/plan/scale', {width_px: IMG.naturalWidth, height_px: IMG.naturalHeight, ft_per_px: ft / imgPx, confirmed: true});
    }
    return;
  }
  const at = toPx(p);
  for (const id of Object.keys(PLAN.boards)) {
    const q = toPx(boardPos(id));
    if (Math.hypot(q[0] - at[0], q[1] - at[1]) < 16) {
      const b = PLAN.boards[id]; DRAG = {id, role: b.role, mac: b.mac, pos: [b.x, b.y]};
      cvL.setPointerCapture(ev.pointerId); return;
    }
  }
});
cvL.addEventListener('pointermove', ev => { if (DRAG) { DRAG.pos = toFt(ev); drawPlan(); } });
cvL.addEventListener('pointerup', () => {
  if (!DRAG) return;
  const d = DRAG;
  post('/plan/board', {id: d.id, role: d.role, mac: d.mac, x: d.pos[0], y: d.pos[1]}).then(() => { if (DRAG === d) DRAG = null; });
});
document.addEventListener('keydown', ev => { if (ev.key === 'Escape') { MODE = null; hint(''); drawPlan(); } });

document.getElementById('zoom-btn').onclick = () => { ZOOM = !ZOOM; if (PLAN) { fitView(); drawPlan(); } };

// ---- accuracy test: the walker clicks where they really are, the page compares with the estimate ----
const TRUTH = {on: false, marks: []};
document.getElementById('truth-btn').onclick = () => {
  TRUTH.on = !TRUTH.on;
  document.getElementById('truth-btn').className = TRUTH.on ? 'active' : '';
  if (TRUTH.on) { TRUTH.marks = []; MODE = null; hint('Accuracy test: walk, and click where you are every few steps. Click the button again to stop.'); }
  else hint('');
  truthStats(); drawPlan();
};
function markTruth(p) {
  const loc = LAST && LAST.location;
  const est = loc && loc.moving ? [loc.x, loc.y] : null;
  TRUTH.marks.push({truth: p, est, seen: !!(loc && (loc.moving || loc.motion_seen)),
                    err: est ? Math.hypot(est[0] - p[0], est[1] - p[1]) : null});
  truthStats(); drawPlan();
}
function truthStats() {
  const m = TRUTH.marks, el = document.getElementById('truth-stats');
  if (!m.length) { el.textContent = TRUTH.on ? 'no clicks yet' : ''; return; }
  const errs = m.filter(x => x.err !== null).map(x => x.err).sort((a, b) => a - b);
  const pct = k => Math.round(100 * k / m.length);
  el.textContent = `${m.length} clicks: motion seen ${pct(m.filter(x => x.seen).length)}%, placed ${pct(errs.length)}%` +
    (errs.length ? `, error median ${errs[Math.floor(errs.length / 2)].toFixed(1)} ft, worst ${errs[errs.length - 1].toFixed(1)} ft` : '');
}

function boardRow(key) {
  if (rows[key]) return rows[key];
  const row = el('div', 'brow'), mark = el('span'), who = el('div', 'who'), name = el('b'), status = el('span');
  const place = el('button', null, 'Place'), del = el('button', null, '×');
  del.title = 'Remove from the plan';
  who.append(name, status); row.append(mark, who, place, del);
  document.getElementById('board-list').append(row);
  return rows[key] = {row, mark, name, status, place, del};
}

function updateBoards(m) {
  const nodes = Object.fromEntries(m.nodes.map(n => [n.id, n]));
  const txByMac = Object.fromEntries((m.transmitters || []).map(t => [t.mac, t]));
  const items = [];
  for (const t of m.transmitters || []) items.push({id: t.id, role: 'tx', mac: t.mac, tx: t});
  for (const [id, b] of Object.entries(PLAN.boards))
    if (b.role === 'tx' && !txByMac[b.mac]) items.push({id, role: 'tx', mac: b.mac, tx: {heardBy: []}});
  const rxIds = new Set([...m.nodes.map(n => n.id), ...Object.entries(PLAN.boards).filter(([, b]) => b.role === 'rx').map(([id]) => id)]);
  for (const id of [...rxIds].sort()) items.push({id, role: 'rx', node: nodes[id]});
  const seen = new Set();
  for (const it of items) {
    const key = it.role + ':' + it.id; seen.add(key);
    const r = boardRow(key), placed = !!PLAN.boards[it.id];
    r.name.textContent = it.id + (it.role === 'tx' ? '  (transmitter)' : '  (receiver)');
    if (it.role === 'tx') {
      r.mark.className = 'sq';
      const h = it.tx.heardBy;
      r.status.textContent = h.length ? 'heard by ' + h.map(x => `${x.rx} (${x.rate}/s)`).join(', ')
                                      : 'not heard by any receiver: powered on? receivers paired to it?';
    } else {
      const n = it.node, st = n ? n.state : 'nosignal';
      r.mark.className = 'dot'; r.mark.style.background = STATE_COLOUR[st] || '#6b7c8f';
      const tx = n && n.txMac ? (txByMac[n.txMac] ? txByMac[n.txMac].id : n.txMac) : null;
      r.status.textContent = !n ? 'not connected to this laptop'
        : (STATE_LABEL[st] || st) + (tx ? ' · listening to ' + tx : '') + ' · ' + n.rate + '/s';
    }
    r.status.textContent += placed ? '' : ' · not placed';
    r.place.textContent = placed ? 'Move' : 'Place';
    r.place.className = MODE && MODE.kind === 'place' && MODE.id === it.id ? 'active' : '';
    r.place.onclick = () => placeBoard(it.id, it.role, it.mac);
    r.del.style.visibility = placed ? 'visible' : 'hidden';
    r.del.onclick = () => removeBoard(it.id);
  }
  for (const key of Object.keys(rows)) if (!seen.has(key)) { rows[key].row.remove(); delete rows[key]; }
}

function txPosFor(link) {
  // while a transmitter is being dragged, its links follow it
  if (DRAG && DRAG.role === 'tx') {
    const b = PLAN.boards[DRAG.id];
    if (b && b.x === link.tx[0] && b.y === link.tx[1]) return DRAG.pos;
  }
  return link.tx;
}

function drawPlan() {
  const m = LAST; if (!m || !PLAN) return;
  const g = gL, s = scale(), [w, h] = dims();
  g.clearRect(0, 0, cvL.width, cvL.height);
  g.fillStyle = '#0b0f14'; g.fillRect(0, 0, cvL.width, cvL.height);
  const [ox, oy] = toPx([0, 0]);
  if (IMG) { g.drawImage(IMG, ox, oy, w * s, h * s); g.fillStyle = 'rgba(11,15,20,0.35)'; g.fillRect(ox, oy, w * s, h * s); }
  else {
    const step = Math.max(VIEW.w, VIEW.h) > 30 ? 5 : 1;  // 1 ft squares on a room, 5 ft on a whole floor
    g.strokeStyle = 'rgba(75,93,112,0.3)'; g.lineWidth = 1;
    for (let f = step; f < w; f += step) { g.beginPath(); g.moveTo(ox + f * s, oy); g.lineTo(ox + f * s, oy + h * s); g.stroke(); }
    for (let f = step; f < h; f += step) { g.beginPath(); g.moveTo(ox, oy + f * s); g.lineTo(ox + w * s, oy + f * s); g.stroke(); }
    if (!(PLAN.plan.walls && PLAN.plan.walls.length)) { g.strokeStyle = '#4b5d70'; g.lineWidth = 2; g.strokeRect(ox, oy, w * s, h * s); }
    g.fillStyle = '#9fb0c0'; g.font = '12px system-ui'; g.fillText(`grid = ${step} ft`, PAD + 6, cvL.height - PAD - 8);
  }
  if (PLAN.plan.walls && PLAN.plan.walls.length) {
    g.strokeStyle = '#8da2b8'; g.lineWidth = 2;
    PLAN.plan.walls.forEach(line => {
      g.beginPath(); line.forEach((p, i) => { const q = toPx(p); i ? g.lineTo(q[0], q[1]) : g.moveTo(q[0], q[1]); }); g.stroke();
    });
  }
  const loc = m.location, lay = m.layout;
  if (loc && lay && loc.grid && loc.grid.covered) {  // areas no working link can see: shaded as unknown
    const {cols, rows: nr, covered} = loc.grid, cw = lay.room[0] * s / cols, ch = lay.room[1] * s / nr;
    const [ox, oy] = toPx(lay.origin);
    g.fillStyle = 'rgba(140,150,165,0.18)';
    covered.forEach((ok, i) => { if (!ok) g.fillRect(ox + (i % cols) * cw, oy + Math.floor(i / cols) * ch, cw + 0.5, ch + 0.5); });
  }
  if (loc && lay && loc.moving) {
    const {cols, rows: nr, cells} = loc.grid, cw = lay.room[0] * s / cols, ch = lay.room[1] * s / nr;
    const [ox, oy] = toPx(lay.origin);
    cells.forEach((v, i) => {
      if (v < 0.15) return;
      g.fillStyle = `rgba(255,159,28,${(v * 0.7).toFixed(2)})`;
      g.fillRect(ox + (i % cols) * cw, oy + Math.floor(i / cols) * ch, cw + 0.5, ch + 0.5);
    });
  }
  const nodes = Object.fromEntries(m.nodes.map(n => [n.id, n]));
  if (lay) lay.links.forEach(l => {
    const st = nodes[l.rx_id] ? nodes[l.rx_id].state : 'nosignal';
    const off = loc && loc.excluded ? loc.excluded[l.rx_id] : null;
    const col = off ? '#6b7c8f' : (STATE_COLOUR[st] || '#6b7c8f');
    const a = toPx(txPosFor(l)), b = toPx(boardPos(l.rx_id) || l.rx);
    g.strokeStyle = col; g.lineWidth = !off && st === 'motion' ? 5 : 2;
    g.setLineDash(!off && (st === 'motion' || st === 'quiet') ? [] : [8, 6]);
    g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke(); g.setLineDash([]);
    if (Math.hypot(a[0] - b[0], a[1] - b[1]) < 4) { g.beginPath(); g.arc(b[0], b[1], 18, 0, 7); g.stroke(); }
    if (off) { g.fillStyle = '#ffb4a8'; g.font = '12px system-ui'; g.fillText('left out: ' + off, b[0] + 13, b[1] + 18); }
  });
  if (loc) loc.trail.forEach((p, i) => {
    const q = toPx(p); g.fillStyle = `rgba(108,182,255,${(0.1 + 0.6 * i / loc.trail.length).toFixed(2)})`;
    g.beginPath(); g.arc(q[0], q[1], 4, 0, 7); g.fill();
  });
  for (const id of Object.keys(PLAN.boards)) {
    const b = PLAN.boards[id], q = toPx(boardPos(id));
    g.lineWidth = 2; g.strokeStyle = '#0b0f14';
    if (b.role === 'tx') { g.fillStyle = '#e6edf3'; g.fillRect(q[0] - 9, q[1] - 9, 18, 18); g.strokeRect(q[0] - 9, q[1] - 9, 18, 18); }
    else {
      const n = nodes[id]; g.fillStyle = STATE_COLOUR[n ? n.state : 'nosignal'] || '#6b7c8f';
      g.beginPath(); g.arc(q[0], q[1], 10, 0, 7); g.fill(); g.stroke();
    }
    const label = id.startsWith('TX@') ? 'TX' : id;
    g.font = 'bold 13px system-ui';
    const tw = g.measureText(label).width, lx = q[0] + 13 + tw > cvL.width - 4 ? q[0] - 13 - tw : q[0] + 13;
    g.lineWidth = 4; g.strokeStyle = '#0b0f14'; g.strokeText(label, lx, q[1] - 10);
    g.fillStyle = '#ffffff'; g.fillText(label, lx, q[1] - 10);
  }
  TRUTH.marks.forEach(k => {  // accuracy test: green cross = where you were, line to the estimate
    const q = toPx(k.truth);
    if (k.est) { const e = toPx(k.est); g.strokeStyle = 'rgba(255,255,255,0.5)'; g.lineWidth = 1; g.beginPath(); g.moveTo(q[0], q[1]); g.lineTo(e[0], e[1]); g.stroke(); }
    g.strokeStyle = k.est ? '#5be49b' : '#ff6b6b'; g.lineWidth = 3;
    g.beginPath(); g.moveTo(q[0] - 6, q[1] - 6); g.lineTo(q[0] + 6, q[1] + 6); g.moveTo(q[0] + 6, q[1] - 6); g.lineTo(q[0] - 6, q[1] + 6); g.stroke();
  });
  if (MODE && MODE.kind === 'scale') MODE.pts.forEach(p => {
    const q = toPx(p); g.fillStyle = '#ffd166'; g.beginPath(); g.arc(q[0], q[1], 6, 0, 7); g.fill();
  });
  const badge = document.getElementById('where-badge'), text = document.getElementById('where-text');
  if (!lay) {
    badge.textContent = 'PLACE BOARDS'; badge.className = 'badge b-warming';
    text.textContent = 'place a transmitter and at least one receiver that listens to it';
  } else if (loc && loc.moving) {
    const q = toPx([loc.x, loc.y]);
    g.strokeStyle = 'rgba(255,255,255,0.8)'; g.lineWidth = 2; g.beginPath(); g.arc(q[0], q[1], loc.spread * s, 0, 7); g.stroke();
    g.fillStyle = '#ffffff'; g.beginPath(); g.arc(q[0], q[1], 9, 0, 7); g.fill();
    badge.textContent = loc.degraded ? 'MOTION (LESS SURE)' : 'MOTION'; badge.className = 'badge b-motion';
    text.textContent = `near x ${loc.x.toFixed(1)} ft, y ${loc.y.toFixed(1)} ft (\u00b1${loc.spread.toFixed(1)} ft)` + (loc.note ? '  ' + loc.note : '');
  } else if (loc && loc.motion_seen) {
    badge.textContent = 'MOTION (CANNOT PLACE)'; badge.className = 'badge b-motion';
    text.textContent = loc.note || 'Motion seen, but not enough working links to place it.';
  } else {
    if (loc && loc.last) {
      const q = toPx(loc.last); g.strokeStyle = '#cdd9e5'; g.lineWidth = 2; g.setLineDash([3, 3]);
      g.beginPath(); g.arc(q[0], q[1], 10, 0, 7); g.stroke(); g.setLineDash([]);
    }
    badge.textContent = 'NO MOTION'; badge.className = 'badge b-quiet';
    text.textContent = loc && loc.last ? 'dashed ring = last place motion was seen. Not moving ≠ not there.' : 'no motion seen yet';
  }
}

const es = new EventSource('/events');
es.onmessage = e => {
  const m = JSON.parse(e.data);
  LAST = m;
  const waiting = document.getElementById('waiting');
  waiting.style.display = m.nodes.length ? 'none' : 'block';
  if (!m.nodes.length && m.ports) waiting.textContent = m.ports.length
    ? 'Watching ' + m.ports.join(', ') + ', waiting for receiver data\u2026'
    : 'No ESP32 plugged in yet. Plug in a receiver; it is picked up automatically.';
  document.getElementById('errors').textContent = Object.entries(m.errors).map(([p, msg]) => `Port ${p}: ${msg}`).join('   ');
  m.nodes.forEach(update);
  if (m.plan) {  // floor plan edited on this page
    document.getElementById('where').style.display = 'block';
    document.getElementById('room').style.display = 'none';
    document.getElementById('room-label').style.display = 'none';
    setPlan(m.plan); updateBoards(m); drawPlan();
  } else if (m.layout) {  // fixed --layout file: nothing to edit
    document.getElementById('where').style.display = 'block';
    document.getElementById('plan-tools').style.display = 'none';
    document.getElementById('plan-side').style.display = 'none';
    document.getElementById('room').style.display = 'none';
    document.getElementById('room-label').style.display = 'none';
    drawLocation(m.layout, m.location, m.nodes);
  } else {
    drawRoom(m.nodes);
  }
  drawTimeline(m.nodes);
};
es.onerror = () => { document.getElementById('waiting').textContent = 'Lost connection to the viewer. Is rs-view still running?'; document.getElementById('waiting').style.display = 'block'; };
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
