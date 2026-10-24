import { describe, expect, it } from "vitest";
import { parseMessage } from "../src/ws/messages";

const room = {
  room_id: "R1",
  state: "MOTION",
  label: "MOTION",
  confidence_band: "high",
  confidence_pct: 86,
  last_seen: 1730000000.0,
  last_evidence: 1730000000.0,
  stale: false,
  last_known_state: null,
  stale_age_s: null,
  calibrated: true,
  searched: false,
  annotation: "responder_present",
  alarm_time_state: "MOTION",
  link_health: "ok",
  source: "edge",
  model_ver: 3,
};

const roomStates = {
  type: "room_states",
  ts: 1730000000.0,
  system_state: "ALARM_ACTIVE",
  simulated: false,
  rooms: [room],
  ranking: ["R1", "R2"],
};

const health = {
  type: "health",
  ts: 1730000000.0,
  summary: "1 fault",
  nodes: [
    { node_id: "RX1", role: "RX", room_id: "R1", status: "ok", measured_pps: 72 },
    {
      node_id: "TX2", role: "TX", room_id: "R2", status: "tx_dead", inferred_from: "RX2",
      cause: "RX2 measured packet rate below 20% for 5 s", action: "check TX2 power",
    },
  ],
  tag_faults: [{ tag_id: "E1", last_room: "R2", silent_s: 12 }],
};

const crew = {
  type: "crew",
  ts: 1730000000.0,
  tags: [{
    tag_id: "E1", location_kind: "room", room_id: "R2", near_rooms: [], confidence_band: "high",
    last_heard_s: 1, marker: "solid", you_are_here: false,
  }],
  floor_crew_counts: { F1: 1 },
};

const recording = { type: "recording", ts: 1730000000.0, indicator: "Recording (alarm)", stored_samples: 128, fault: null };

const j = (v: unknown) => JSON.stringify(v);

describe("parseMessage", () => {
  it("accepts the parent design's example of each message type", () => {
    expect(parseMessage(j(roomStates))).toEqual(roomStates);
    expect(parseMessage(j(health))).toEqual(health);
    expect(parseMessage(j(crew))).toEqual(crew);
    expect(parseMessage(j(recording))).toEqual(recording);
  });

  it("requires NO_DETECTION to carry the label 'NO DETECTION'", () => {
    const ok = { ...roomStates, rooms: [{ ...room, state: "NO_DETECTION", label: "NO DETECTION" }] };
    expect(parseMessage(j(ok))).not.toBeNull();
    const bad = { ...roomStates, rooms: [{ ...room, state: "NO_DETECTION", label: "NO_DETECTION" }] };
    expect(parseMessage(j(bad))).toBeNull();
    const mismatch = { ...roomStates, rooms: [{ ...room, state: "MOTION", label: "POSSIBLE" }] };
    expect(parseMessage(j(mismatch))).toBeNull();
  });

  it("rejects bad enums, types, ranges, and missing fields", () => {
    expect(parseMessage(j({ ...roomStates, system_state: "FIRE" }))).toBeNull();
    expect(parseMessage(j({ ...roomStates, rooms: [{ ...room, confidence_pct: 101 }] }))).toBeNull();
    expect(parseMessage(j({ ...roomStates, rooms: [{ ...room, confidence_pct: -1 }] }))).toBeNull();
    expect(parseMessage(j({ ...roomStates, rooms: [{ ...room, stale: "no" }] }))).toBeNull();
    const { model_ver: _omit, ...noModelVer } = room;
    expect(parseMessage(j({ ...roomStates, rooms: [noModelVer] }))).toBeNull();
    expect(parseMessage(j({ ...recording, ts: "now" }))).toBeNull();
    expect(parseMessage(j({ ...crew, floor_crew_counts: { F1: "1" } }))).toBeNull();
    expect(parseMessage(j({ type: "auth", ts: 1 }))).toBeNull();
  });

  it("never throws on garbage input", () => {
    for (const raw of ["", "not json", "null", "[]", "42", '"x"', "{}", '{"type":"health"}']) {
      expect(() => parseMessage(raw)).not.toThrow();
      expect(parseMessage(raw)).toBeNull();
    }
  });
});
