"""LiveSource: room states from real receivers (or a replay / the board simulator).

Lines from the receivers' serial ports go through beacon_hub (firmware/tools): the protocol
parser, packet-loss tracking, and each link's MOTION / QUIET / WEAK state with receiver-gain
correction. room_engine.py turns the links of each room into one of the four room states.

Which room a receiver belongs to comes from the floor plan (hub/config/floorplan.json), not
from the board's room_id setting, so the plan and the data cannot disagree silently: a
mismatch is logged once. Rooms marked "simulated" in the floor plan are filled from the
scripted mock when `with_sim` is on, and every message then carries simulated: true. Any other
room with no receiver is reported UNKNOWN ("no sensors") for the whole incident, so it is ranked
for a search instead of silently missing.

A receiver the viewer would leave out of its motion map (losing packets, glitching, clipping) is
not judged here either: its room falls back to its other receivers, or to UNKNOWN.

Privacy: transmitter MACs, raw CSI and activity numbers stay in this process (RAM only).
Messages carry room-level state and node names only. Nothing is written to disk. In IDLE the
engine keeps running in memory (the rolling buffer) but room_states carries no rooms.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable

from beacon_hub import TagSummary, format_record, parse_line
from beacon_hub.viewer import Hub as LinkHub

from . import room_engine, scripted
from .room_engine import LinkReading, RoomTrack
from .source import Broadcaster, Message
from .tag_locator import TagLocator

log = logging.getLogger("hub.live")

TICK_S = 0.5
TX_DEAD_AFTER_S = 5.0
RESPONDER_LEFT_NOTE_S = 60.0  # "recent motion may be responder" this long after a tag leaves a room


class _Links(LinkHub):
    """The viewer's link hub, plus a hook so TAG summaries reach the tag locator. Serial and
    replay readers call feed_line on this object directly."""

    def __init__(self, on_tag: Callable[[TagSummary, float], None]):
        super().__init__()
        self._on_tag = on_tag
        self.ml = None  # optional MLClassifier: sees every line, changes nothing here

    def feed_line(self, line: str, now: float | None = None, port: str | None = None) -> None:
        now = time.time() if now is None else now
        super().feed_line(line, now, port)
        if self.ml is not None:
            self.ml.feed_line(line)
        if line.startswith("TAG,"):
            rec = parse_line(line)
            if isinstance(rec, TagSummary):
                self._on_tag(rec, now)


class FloorplanLinks:
    """Receivers, transmitters and rooms as the floor plan places them."""

    def __init__(self, plan: dict):
        self.room_ids: list[str] = [r["id"] for f in plan["floors"] for r in f["rooms"]]
        self.room_floor: dict[str, str] = {r["id"]: f["id"] for f in plan["floors"] for r in f["rooms"]}
        self.simulated: set[str] = {r["id"] for f in plan["floors"] for r in f["rooms"] if r.get("simulated")}
        nodes = {n["id"]: n for n in plan.get("nodes", [])}
        self.rx_room: dict[str, str] = {i: n["room"] for i, n in nodes.items() if n["role"] == "RX"}
        self.tx_room: dict[str, str] = {i: n["room"] for i, n in nodes.items() if n["role"] == "TX"}
        self.tx_receivers: dict[str, list[str]] = {}
        for link in plan.get("links", []):
            self.tx_receivers.setdefault(link["tx"], []).append(link["rx"])
        self.live_rooms: list[str] = [r for r in self.room_ids if r in set(self.rx_room.values())]
        self.unsensed: list[str] = [r for r in self.room_ids if r not in self.live_rooms and r not in self.simulated]

    def receivers_in(self, room_id: str) -> list[str]:
        return sorted(rx for rx, room in self.rx_room.items() if room == room_id)

    @classmethod
    def load(cls, path: Path) -> "FloorplanLinks":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))


class LiveSource(Broadcaster):
    def __init__(self, floorplan: Path, *, hold_s: float = room_engine.HOLD_S, with_sim: bool = True,
                 sim_speed: float = 1.0, clock: Callable[[], float] = time.time, tick_s: float = TICK_S,
                 ml_model: Path | None = None):
        super().__init__()
        self.plan = FloorplanLinks.load(floorplan)
        self.links = _Links(self._on_tag)
        if ml_model is not None:  # extra ML line under each room; the room state logic is unchanged
            from .ml_classifier import MLClassifier
            self.links.ml = MLClassifier(ml_model)
        self.tags = TagLocator(self.plan.live_rooms)
        self._tag_lock = threading.Lock()
        self._tag_room: dict[str, str] = {}  # tag -> room it was last located in (medium/high)
        self._tag_left: dict[str, float] = {}  # room -> when a tag last left it
        self.hold_s = hold_s
        self.with_sim = with_sim and bool(self.plan.simulated)
        self.sim_speed = sim_speed
        self._clock = clock
        self._tick_s = tick_s
        self._tracks = {r: RoomTrack(r) for r in self.plan.live_rooms}
        self._entries: dict[str, dict] = {}
        self._alarm_at: float | None = None
        self._sim_clock: scripted.Clock | None = None
        self._snapshot: dict[str, str | None] = {}
        self._searched: set[str] = set()
        self._tx_low_since: dict[str, float] = {}
        self._warned: set[str] = set()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._task: asyncio.Task | None = None
        if not self.plan.live_rooms:
            raise ValueError("The floor plan has no receiver (role RX) in any room, so there is nothing live to show.")

    # --- inputs --------------------------------------------------------------
    def feed_line(self, line: str, now: float | None = None) -> None:
        """Thread-safe: called by serial/replay/simulator threads, or directly by tests."""
        self.links.feed_line(line, self._clock() if now is None else now)

    def _on_tag(self, summary: TagSummary, now: float) -> None:
        # Tags are located only during an incident; in IDLE their summaries are dropped (Req 29.2).
        room = self.plan.rx_room.get(summary.node_id)
        if self._alarm_at is None or room is None:
            return
        with self._tag_lock:
            self.tags.on_summary(summary.tag_id, room, summary.mean_rssi, now)

    def add_tag_simulator(self, tag_id: str = "E1", room_id: str | None = None) -> None:
        """A responder tag standing in one live room, heard by that room's receivers once a
        second (for trying the crew marker without a tag board)."""
        room = room_id or self.plan.live_rooms[0]
        rxs = self.plan.receivers_in(room)

        def run() -> None:
            import random

            rng = random.Random(3)
            while not self._stop.wait(1.0):
                for rx in rxs:
                    rssi = -55 + rng.gauss(0, 2)
                    self.feed_line(format_record(TagSummary(rx, room, tag_id, 10, round(rssi, 1), round(rssi) + 2)))

        self._spawn(run)

    def add_serial_port(self, port: str, baud: int = 921600) -> None:
        from beacon_hub.viewer import serial_reader

        self._spawn(serial_reader, self.links, port, baud, self._stop)

    def add_replay(self, path: Path) -> None:
        from beacon_hub.viewer import replay_reader

        self._spawn(replay_reader, self.links, Path(path), self._stop)

    def add_board_simulator(self, layout_path: Path) -> None:
        """Fake receivers from firmware/tools (a person walking a loop), for trying without boards."""
        from beacon_hub.locate import load_layout
        from beacon_hub.simulate import run

        self._spawn(run, load_layout(layout_path), self.feed_line, self._stop)

    def add_evacuation_sim(self, data_dir: Path) -> None:
        """Demo: fake receivers in the simulated rooms replay recorded CSI as an evacuation (hub/evac_sim.py)."""
        from . import evac_sim

        links = [{"tx": tx, "rx": rx} for tx, rxs in self.plan.tx_receivers.items() for rx in rxs
                 if self.plan.rx_room.get(rx) in self.plan.simulated]
        self._spawn(evac_sim.run, self.feed_line, lambda: self._alarm_at, links, self.plan.rx_room,
                    Path(data_dir), self._stop)

    def _spawn(self, target, *args) -> None:
        t = threading.Thread(target=target, args=args, daemon=True)
        self._threads.append(t)
        if self._task is not None:  # already started
            t.start()

    # --- StateSource -----------------------------------------------------------
    def room_ids(self) -> set[str]:
        ids = set(self.plan.live_rooms) | set(self.plan.unsensed)
        if self.with_sim:
            ids |= self.plan.simulated & set(scripted.ROOM_IDS)
        return ids

    async def start(self) -> None:
        for t in self._threads:
            if not t.is_alive():
                t.start()
        self.tick()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def trigger_alarm(self) -> Message:
        if self._alarm_at is None:  # idempotent while ALARM_ACTIVE
            now = self._clock()
            self._alarm_at = now
            self._searched.clear()
            self._reset_tags()
            # The alarm-time snapshot comes from the rolling (RAM-only) engine state.
            self._snapshot = {r: e["state"] for r, e in self._entries.items()}
            self._snapshot.update({r: "UNKNOWN" for r in self.plan.unsensed})
            if self.with_sim:
                self._sim_clock = scripted.Clock(now, self.sim_speed)
                # only rooms the plan marks simulated: a real room may share an id with the script's
                self._snapshot.update({r: s for r, s in scripted.alarm_snapshot(self._sim_clock).items()
                                       if r in self.plan.simulated})
            self.publish_frame(now)
        return {"system_state": "ALARM_ACTIVE", "simulated": self.with_sim}

    async def end_incident(self) -> Message:
        self._alarm_at = None
        self._sim_clock = None
        self._snapshot = {}
        self._searched.clear()
        self._reset_tags()  # tag positions live only for the incident (Req 29.4)
        self.publish_frame(self._clock())
        return {"system_state": "IDLE", "simulated": self.with_sim}

    def _reset_tags(self) -> None:
        with self._tag_lock:
            self.tags.reset()
            self._tag_room.clear()
            self._tag_left.clear()

    def _crew(self, now: float, readings: dict[str, LinkReading]) -> tuple[Message, list[dict]]:
        degraded = {self.plan.rx_room[rx] for rx, r in readings.items() if r.online() and not r.healthy()}
        offline = any(not r.online() for r in readings.values())
        with self._tag_lock:
            crew = self.tags.crew_message(now, self.plan.room_floor, degraded, offline)
            faults = self.tags.lost_faults(now)
            for t in crew["tags"]:
                located = t["room_id"] if t["location_kind"] == "room" else None
                prev = self._tag_room.get(t["tag_id"])
                if prev and prev != located:
                    self._tag_left[prev] = now
                if located:
                    self._tag_room[t["tag_id"]] = located
                else:
                    self._tag_room.pop(t["tag_id"], None)
        return crew, faults

    async def mark_searched(self, room_id: str) -> None:
        if room_id not in self.room_ids():
            raise KeyError(room_id)
        if self._alarm_at is not None:
            self._searched.add(room_id)
            self.publish_frame(self._clock())

    # --- ticking -----------------------------------------------------------
    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._tick_s)
            self.tick()

    def tick(self, now: float | None = None) -> None:
        now = self._clock() if now is None else now
        readings = self._readings(now)
        for room_id, track in self._tracks.items():
            room_readings = [readings[rx] for rx in self.plan.receivers_in(room_id) if rx in readings]
            latch_after = None if self._alarm_at is None else self._alarm_at - room_engine.PRE_ALARM_S
            self._entries[room_id] = room_engine.update(track, room_readings, now, self.hold_s, latch_after)
            if self.links.ml is not None:
                self._entries[room_id]["ml"] = self.links.ml.room(self.plan.receivers_in(room_id))
        self._health = self._health_msg(readings, now)
        if self._alarm_at is not None:
            self._crew_msg, self._health["tag_faults"] = self._crew(now, readings)
            n_faults = sum(n["status"] != "ok" for n in self._health["nodes"]) + len(self._health["tag_faults"])
            self._health["summary"] = "All sensors online" if n_faults == 0 else \
                f"{n_faults} fault" + ("s" if n_faults > 1 else "")
        else:
            self._crew_msg = None
        self.publish_frame(now)

    def _readings(self, now: float) -> dict[str, LinkReading]:
        out: dict[str, LinkReading] = {}
        with self.links.lock:
            for node_id, node in self.links.nodes.items():
                if node_id not in self.plan.rx_room:
                    self._warn_once(f"unknown:{node_id}", "Receiver %s is sending data but is not on the floor plan; "
                                    "add it to hub/config/floorplan.json nodes to use it.", node_id)
                    continue
                hb = node.heartbeat
                if hb is not None and hb.room_id != self.plan.rx_room[node_id]:
                    self._warn_once(f"room:{node_id}", "Receiver %s reports room_id=%s but the floor plan puts it in %s; "
                                    "using the floor plan.", node_id, hb.room_id, self.plan.rx_room[node_id])
                activity, threshold = node.update_state(now)
                score = None if activity is None or not threshold else activity / threshold
                hb_age = None if node.heartbeat_t is None else now - node.heartbeat_t
                fault = None
                if node.state in room_engine.USABLE_STATES and hb_age is not None and hb_age <= room_engine.HB_OFFLINE_S:
                    rate = sum(1 for t in node.times if now - t <= 1.0)
                    fault = node.off_reason(now, True, rate)
                out[node_id] = LinkReading(node_id, node.state, score, hb_age, hb.measured_pps if hb else None, fault)
        for rx in self.plan.rx_room:  # receivers never heard from
            out.setdefault(rx, LinkReading(rx, "nosignal", None, None, None))
        return out

    def _warn_once(self, key: str, msg: str, *args) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning(msg, *args)

    # --- messages -----------------------------------------------------------
    def _health_msg(self, readings: dict[str, LinkReading], now: float) -> Message:
        nodes: list[dict] = []
        for rx in sorted(self.plan.rx_room):
            r = readings[rx]
            node = {"node_id": rx, "role": "RX", "room_id": self.plan.rx_room[rx], "status": "ok",
                    "measured_pps": r.pps or 0}
            if not r.online():
                node.update(status="offline", cause=f"No {rx} heartbeat for {int(room_engine.HB_OFFLINE_S)} s",
                            action=f"Check {rx} power and USB cable")
            elif r.hb_age is not None and r.hb_age > room_engine.HB_DEGRADED_S:
                node.update(status="degraded", cause=f"{rx} heartbeat late (over 3 s)",
                            action=f"Check {rx} USB cable")
            elif r.fault:
                node.update(status="degraded", cause=f"{rx} not judged: {r.fault}",
                            action=f"Check {rx}'s antenna and its distance to the transmitter")
            elif r.state == "weak":
                node.update(status="degraded", cause=f"{rx} signal too weak or flat to judge",
                            action="Check the antenna is not covered and the boards face each other")
            nodes.append(node)
        for tx in sorted(self.plan.tx_room):
            rxs = [readings[r] for r in self.plan.tx_receivers.get(tx, []) if r in readings]
            node = {"node_id": tx, "role": "TX", "room_id": self.plan.tx_room[tx], "status": "ok",
                    "inferred_from": ",".join(r.node_id for r in rxs)}
            online = [r for r in rxs if r.online()]
            low = bool(online) and all((r.pps or 0) < room_engine.PPS_MIN for r in online)
            if low:
                self._tx_low_since.setdefault(tx, now)
            else:
                self._tx_low_since.pop(tx, None)
            if not online:
                node.update(status="offline", cause=f"{tx} cannot be checked while its receivers are offline",
                            action="Restore the receivers first")
            elif low and now - self._tx_low_since[tx] >= TX_DEAD_AFTER_S:
                node.update(status="tx_dead", cause="Receiver packet rate below 20% for 5 s",
                            action=f"Check {tx} power")
            nodes.append(node)
        faults = sum(n["status"] != "ok" for n in nodes)
        summary = "All sensors online" if faults == 0 else f"{faults} fault" + ("s" if faults > 1 else "")
        return {"type": "health", "ts": now, "summary": summary, "nodes": nodes, "tag_faults": []}

    def frame(self, now: float) -> dict[str, Message]:
        health = getattr(self, "_health", None) or self._health_msg(self._readings(now), now)
        crew = getattr(self, "_crew_msg", None) if self._alarm_at is not None else None
        crew = crew or {"type": "crew", "ts": now, "tags": [], "floor_crew_counts": {}}
        if self._alarm_at is None:
            return {
                "room_states": {"type": "room_states", "ts": now, "system_state": "IDLE",
                                "simulated": self.with_sim, "rooms": [], "ranking": []},
                "health": health,
                "crew": crew,
                "recording": {"type": "recording", "ts": now, "indicator": "Not recording",
                              "stored_samples": 0, "fault": None},
            }
        rooms = [dict(self._entries[r]) for r in self.plan.live_rooms if r in self._entries]
        rooms += [room_engine.unsensed_entry(r) for r in self.plan.unsensed]
        if self.with_sim and self._sim_clock is not None:
            vt = (now - self._sim_clock.alarm_ts) * self.sim_speed
            rooms += [r for r in scripted.room_list(vt, self._sim_clock) if r["room_id"] in self.plan.simulated]
        present = {t["room_id"] for t in crew["tags"]
                   if t["location_kind"] == "room" and t["confidence_band"] in ("medium", "high")}
        for r in rooms:
            r["searched"] = r["room_id"] in self._searched
            r["alarm_time_state"] = self._snapshot.get(r["room_id"])
            # Labels only: a responder never hides or downgrades a room's state (Req 27.1-27.3).
            if r["room_id"] in self._entries:
                if r["state"] == "MOTION" and r["room_id"] in present:
                    r["annotation"] = "responder_present"
                elif r["state"] == "POSSIBLE" and r["room_id"] not in present and \
                        now - self._tag_left.get(r["room_id"], -1e9) < RESPONDER_LEFT_NOTE_S:
                    r["annotation"] = "recent_motion_may_be_responder"
        return {
            "room_states": {"type": "room_states", "ts": now, "system_state": "ALARM_ACTIVE",
                            "simulated": self.with_sim, "rooms": rooms, "ranking": scripted.rank(rooms)},
            "health": health,
            "crew": crew,
            "recording": {"type": "recording", "ts": now, "indicator": "Recording (alarm)",
                          "stored_samples": len(rooms) * (1 + int((now - self._alarm_at) / self._tick_s)),
                          "fault": None},
        }

    def publish_frame(self, now: float) -> None:
        for msg in self.frame(now).values():
            self.publish(msg)
