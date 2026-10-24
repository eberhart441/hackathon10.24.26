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
import statistics
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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
# A receiver is "obviously off" and left out of the location estimate when any of these hold.
OFF_MIN_RATE = 40         # CSI lines/s; healthy links run at about 95 to 105
OFF_GLITCHES_10S = 15     # glitch packets in the last 10 s; healthy links show about 3
OFF_CLIPPED = 0.25        # share of subcarriers stuck at 255 (too close to the transmitter, or gain wrong)


class NodeView:
    """Everything the page shows for one receiver."""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.window: deque[tuple[int, ...]] = deque(maxlen=WINDOW)
        self.recent: deque[tuple[int, ...]] = deque(maxlen=5)
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
        # Single packets sometimes arrive with every subcarrier about 3x too strong (the receiver's
        # gain setting, which the classic ESP32 does not report). A 5-packet median per subcarrier
        # removes those one-packet spikes without hiding real, sustained motion.
        self.recent.append(rec.amplitudes)
        self.window.append(tuple(int(statistics.median(col)) for col in zip(*self.recent)))
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
        """Average strength of the most recent packet over subcarriers that carry signal."""
        if not self.window:
            return None
        live = [a for a in self.window[-1] if a]
        return statistics.mean(live) if live else 0.0

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
            self.baseline = 0.98 * self.baseline + 0.02 * activity  # learn only while quiet
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
        if rate < OFF_MIN_RATE:
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

    def __init__(self, layout: Layout | None = None) -> None:
        self.lock = threading.Lock()
        self.layout = layout
        self.locator = Locator(layout) if layout else None
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
            message = {"t": now, "nodes": nodes, "errors": errors}
            if self.locator is not None:
                scores: dict[str, float | None] = {}
                excluded: dict[str, str] = {}
                for link in self.layout.links:
                    node = self.nodes.get(link.rx_id)
                    snap = next((n for n in nodes if n["id"] == link.rx_id), None)
                    if node is None or snap is None:
                        scores[link.rx_id] = None
                        excluded[link.rx_id] = "not connected"
                        continue
                    scores[link.rx_id] = link_score(snap["state"], snap["activity"], node.baseline, snap["threshold"])
                    if snap["offReason"]:
                        excluded[link.rx_id] = snap["offReason"]
                message["layout"] = self.layout.to_json()
                message["location"] = self.locator.update(scores, excluded)
        return json.dumps(message)

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

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                body = PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
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
            if self.path == "/reset":
                hub.reset_baselines()
                self.send_response(204)
                self.end_headers()
            else:
                self.send_error(404)

    return Handler


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", action="append", default=[], help="receiver serial port (repeat for several)")
    p.add_argument("--baud", type=int, default=921600)
    p.add_argument("--replay", type=Path, help="play back a captured log instead of reading hardware")
    p.add_argument("--layout", type=Path,
                   help="room and link positions (JSON) for the motion location map, for example layouts/demo-room.json")
    p.add_argument("--simulate", action="store_true",
                   help="fake receivers with a virtual walker, using --layout (default layouts/demo-room.json)")
    p.add_argument("--http-port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args(argv)
    if not args.port and not args.replay and not args.simulate:
        p.error("give at least one --port (for example --port COM3), --replay FILE, or --simulate")
    if args.simulate and not args.layout:
        args.layout = DEFAULT_LAYOUT
    layout = load_layout(args.layout) if args.layout else None

    hub, stop = Hub(layout), threading.Event()
    threads = [threading.Thread(target=ticker, args=(hub, stop), daemon=True)]
    for port in args.port:
        threads.append(threading.Thread(target=serial_reader, args=(hub, port, args.baud, stop), daemon=True))
    if args.replay:
        threads.append(threading.Thread(target=replay_reader, args=(hub, args.replay, stop), daemon=True))
    if args.simulate:
        from .simulate import run as simulate
        threads.append(threading.Thread(target=simulate, args=(layout, hub.feed_line, stop), daemon=True))
    for t in threads:
        t.start()

    server = ThreadingHTTPServer(("127.0.0.1", args.http_port), make_handler(hub))
    url = f"http://127.0.0.1:{args.http_port}"
    print(f"RoomSense live view at {url}  (Ctrl+C to stop)")
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
<title>RoomSense live view</title>
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
</style>
</head>
<body>
<h1>RoomSense live view</h1>
<p class="note">Raw signal from the receiver, for checking the boards. The badge is a simple demo indicator,
not the detection model, and &ldquo;quiet&rdquo; never means a room is empty. Walk between the two boards and watch the picture change.</p>
<div id="errors"></div>
<div id="waiting">Waiting for data from the receiver&hellip;</div>
<div class="card" id="where" style="display:none">
  <div class="head"><div class="title">Where is the motion?</div><span class="badge" id="where-badge"></span><span class="sub" id="where-text"></span></div>
  <div class="label">Estimated from which links are disturbed: a zone about 1 to 2 m across, for one moving person. Orange = likely area,
  white dot = estimate (ring = uncertainty), faded dots = recent path. Someone who stops moving drops off the map; that never means they left.</div>
  <canvas id="locate" width="800" height="560"></canvas>
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

const es = new EventSource('/events');
es.onmessage = e => {
  const m = JSON.parse(e.data);
  document.getElementById('waiting').style.display = m.nodes.length ? 'none' : 'block';
  document.getElementById('errors').textContent = Object.entries(m.errors).map(([p, msg]) => `Port ${p}: ${msg}`).join('   ');
  m.nodes.forEach(update);
  if (m.layout) {
    document.getElementById('where').style.display = 'block';
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
