import { afterEach, describe, expect, it } from "vitest";
import {
  discard,
  dispatch,
  getState,
  initialState,
  reduce,
  resetStore,
  subscribe,
} from "../src/store/store";
import type { CrewMsg, RoomEntry, RoomStatesMsg } from "../src/ws/messages";

function room(id: string, over: Partial<RoomEntry> = {}): RoomEntry {
  return {
    room_id: id,
    state: "MOTION",
    label: "MOTION",
    confidence_band: "high",
    confidence_pct: 90,
    last_seen: 100,
    last_evidence: 100,
    stale: false,
    last_known_state: null,
    stale_age_s: null,
    calibrated: true,
    searched: false,
    annotation: null,
    alarm_time_state: "MOTION",
    link_health: "ok",
    source: "edge",
    model_ver: 1,
    ...over,
  };
}

function roomStates(system_state: RoomStatesMsg["system_state"], rooms: RoomEntry[]): RoomStatesMsg {
  return { type: "room_states", ts: 1, system_state, simulated: false, rooms, ranking: rooms.map((r) => r.room_id) };
}

const crew: CrewMsg = {
  type: "crew",
  ts: 1,
  tags: [
    {
      tag_id: "t1",
      location_kind: "room",
      room_id: "r1",
      near_rooms: [],
      confidence_band: "high",
      last_heard_s: 1,
      marker: "solid",
      you_are_here: false,
    },
  ],
  floor_crew_counts: { "1": 1 },
};

afterEach(() => resetStore());

describe("reduce", () => {
  it("sets lastMessageAt to the receipt time for every message type", () => {
    const s = reduce(initialState(), crew, 1234);
    expect(s.lastMessageAt).toBe(1234);
    expect(s.crew).toBe(crew);
  });

  it("records the displayed label per room in ALARM_ACTIVE, using last_known_state when stale", () => {
    const m = roomStates("ALARM_ACTIVE", [
      room("r1"),
      room("r2", { state: "UNKNOWN", label: "UNKNOWN", stale: true, last_known_state: "NO_DETECTION", stale_age_s: 30 }),
    ]);
    const s = reduce(initialState(), m, 10);
    expect(s.roomStates).toBe(m);
    expect(s.lastKnown).toEqual({ r1: "MOTION", r2: "NO DETECTION" });
  });

  it("purges rooms, ranking, crew tags, and lastKnown on IDLE", () => {
    let s = reduce(initialState(), crew, 1);
    s = reduce(s, roomStates("ALARM_ACTIVE", [room("r1")]), 2);
    s = reduce(s, roomStates("IDLE", [room("r1")]), 3);
    expect(s.roomStates?.system_state).toBe("IDLE");
    expect(s.roomStates?.rooms).toEqual([]);
    expect(s.roomStates?.ranking).toEqual([]);
    expect(s.crew?.tags).toEqual([]);
    expect(s.lastKnown).toEqual({});
    expect(s.lastMessageAt).toBe(3);
  });

  it("does not mutate its inputs", () => {
    const prev = reduce(initialState(), crew, 1);
    const m = roomStates("IDLE", [room("r1")]);
    const prevSnap = structuredClone(prev);
    const mSnap = structuredClone(m);
    reduce(prev, m, 2);
    reduce(prev, roomStates("ALARM_ACTIVE", [room("r2")]), 3);
    expect(prev).toEqual(prevSnap);
    expect(m).toEqual(mSnap);
  });
});

describe("discard", () => {
  it("increments the counter without touching lastMessageAt", () => {
    const s0 = initialState();
    const s1 = discard(discard(s0));
    expect(s1.discarded).toBe(2);
    expect(s1.lastMessageAt).toBeNull();
    expect(s0.discarded).toBe(0);
  });
});

describe("module store", () => {
  it("dispatches, notifies subscribers, and unsubscribes", () => {
    const seen: number[] = [];
    const unsub = subscribe((s) => seen.push(s.discarded));
    dispatch(null, 5);
    dispatch(crew, 6);
    unsub();
    dispatch(null, 7);
    expect(seen).toEqual([1, 1]);
    expect(getState().discarded).toBe(2);
    expect(getState().lastMessageAt).toBe(6);
  });
});
