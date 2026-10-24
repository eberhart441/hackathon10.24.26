import { describe, expect, it } from "vitest";
import type { FloorPlan } from "../src/floorplan/types";
import { initialState } from "../src/store/store";
import type { StoreState } from "../src/store/store";
import type { RoomEntry, RoomStatesMsg } from "../src/ws/messages";
import { labelFor } from "../src/ws/messages";
import { centroid } from "../src/scene/geometry";
import { buildSceneModel, flagged } from "../src/scene/model";
import type { RoomDescriptor, SceneModel } from "../src/scene/model";
import { STATE_PALETTE } from "../src/scene/palette";
import { BANNED } from "../src/scene/strings";

const plan: FloorPlan = {
  floors: [
    {
      id: "F1",
      name: "Floor 1",
      rooms: [
        { id: "R1", name: "Conference", polygon: [[0, 0], [4, 0], [4, 2], [0, 2]], doors: [], furniture: [], crewSlot: [1, 1] },
        { id: "R2", name: "Storage", polygon: [[4, 0], [6, 0], [6, 2], [4, 2]], doors: [], furniture: [], crewSlot: [5, 1] },
      ],
    },
    {
      id: "F2",
      name: "Floor 2",
      rooms: [
        { id: "R3", name: "Office", polygon: [[0, 0], [2, 0], [2, 2], [0, 2]], doors: [], furniture: [], crewSlot: [1, 1], simulated: true },
      ],
    },
  ],
  nodes: [],
  links: [],
};

const NOW_MS = 1_700_000_100_000; // epoch ms
const NOW_S = NOW_MS / 1000;

function room(id: string, over: Partial<RoomEntry> = {}): RoomEntry {
  const state = over.state ?? "MOTION";
  return {
    room_id: id,
    state,
    label: labelFor(state),
    confidence_band: "high",
    confidence_pct: 86,
    last_seen: NOW_S - 42,
    last_evidence: NOW_S - 42,
    stale: false,
    last_known_state: null,
    stale_age_s: null,
    calibrated: true,
    searched: false,
    annotation: null,
    alarm_time_state: "POSSIBLE",
    link_health: "ok",
    source: "edge",
    model_ver: 1,
    ...over,
  };
}

function store(rooms: RoomEntry[], over: Partial<RoomStatesMsg> = {}, s: Partial<StoreState> = {}): StoreState {
  const msg: RoomStatesMsg = {
    type: "room_states",
    ts: NOW_S,
    system_state: "ALARM_ACTIVE",
    simulated: false,
    rooms,
    ranking: rooms.map((r) => r.room_id),
    ...over,
  };
  return { ...initialState(), roomStates: msg, lastMessageAt: NOW_MS - 1000, ...s };
}

function get(m: SceneModel, id: string): RoomDescriptor {
  const d = m.rooms.find((r) => r.roomId === id);
  if (!d) throw new Error(`no descriptor for ${id}`);
  return d;
}

describe("geometry", () => {
  it("centroid of a rectangle is its center", () => {
    expect(centroid([[0, 0], [4, 0], [4, 2], [0, 2]])).toEqual([2, 1]);
  });
  it("centroid of a degenerate polygon falls back to the vertex mean", () => {
    expect(centroid([[0, 0], [2, 0], [4, 0]])).toEqual([2, 0]);
  });
});

describe("buildSceneModel rule table", () => {
  it("step 1: IDLE shows no label, rank, pattern, or fill even with entries", () => {
    const s = store([room("R1"), room("R2")], { system_state: "IDLE" });
    const m = buildSceneModel(plan, s, NOW_MS, "open");
    expect(m.mode).toBe("idle");
    expect(m.priority).toEqual([]);
    expect(m.snapshot).toEqual([]);
    for (const d of m.rooms) {
      expect(d.treatment).toBe("NONE");
      expect(d.label).toBeNull();
      expect(d.rank).toBeNull();
      expect(d.pattern).toBeNull();
      expect(d.fill).toBeNull();
      expect(d.halo).toBe(false);
    }
    expect(m.rooms.map((d) => d.roomId)).toEqual(["R1", "R2", "R3"]);
  });

  it("step 1: no room_states yet is idle", () => {
    const m = buildSceneModel(plan, initialState(), NOW_MS, "connecting");
    expect(m.mode).toBe("idle");
    expect(m.banners.hubLost).toBe(false);
    expect(m.rooms.every((d) => d.treatment === "NONE")).toBe(true);
  });

  it("step 2: hub lost at exactly 5 s greys rooms and shows STALE text", () => {
    const base = store([room("R1"), room("R2")], {}, { lastKnown: { R1: "MOTION" } });
    const before = buildSceneModel(plan, { ...base, lastMessageAt: NOW_MS - 4999 }, NOW_MS, "open");
    expect(before.banners.hubLost).toBe(false);
    expect(before.rooms.some((d) => d.greyed)).toBe(false);

    const m = buildSceneModel(plan, { ...base, lastMessageAt: NOW_MS - 5000 }, NOW_MS, "open");
    expect(m.banners.hubLost).toBe(true);
    expect(m.rooms.every((d) => d.greyed)).toBe(true);
    expect(get(m, "R1").subText).toContain("STALE — last known MOTION, 0:05 ago");
    // Composes on top of the normal treatment.
    expect(get(m, "R1").treatment).toBe("MOTION");
    expect(get(m, "R2").subText.some((t) => t.startsWith("STALE"))).toBe(false);
  });

  it("step 3: plan room missing from the message is UNKNOWN with No data from hub", () => {
    const m = buildSceneModel(plan, store([room("R1")]), NOW_MS, "open");
    const d = get(m, "R2");
    expect(d.treatment).toBe("UNKNOWN");
    expect(d.label).toBe("UNKNOWN");
    expect(d.subText).toContain("No data from hub");
    expect(d.confidenceText).toBeNull();
  });

  it("step 4: stale room is UNKNOWN with last-known text", () => {
    const s = store([room("R1", { state: "MOTION", stale: true, last_known_state: "POSSIBLE", stale_age_s: 40 })]);
    const d = get(buildSceneModel(plan, s, NOW_MS, "open"), "R1");
    expect(d.treatment).toBe("UNKNOWN");
    expect(d.label).toBe("UNKNOWN");
    expect(d.subText).toEqual(["last known POSSIBLE, 0:40 ago"]);
  });

  it("step 5: uncalibrated room is UNKNOWN with the Uncalibrated chip", () => {
    const s = store([room("R1", { state: "NO_DETECTION", calibrated: false })]);
    const d = get(buildSceneModel(plan, s, NOW_MS, "open"), "R1");
    expect(d.treatment).toBe("UNKNOWN");
    expect(d.chips).toContain("Uncalibrated");
    expect(d.subText).not.toContain("Still needs a sweep");
  });

  it("step 6: normal room passes state through with age and sweep text", () => {
    const s = store([room("R1"), room("R2", { state: "NO_DETECTION", confidence_band: "low", confidence_pct: 34 })]);
    const m = buildSceneModel(plan, s, NOW_MS, "open");
    const r1 = get(m, "R1");
    expect(r1.treatment).toBe("MOTION");
    expect(r1.fill).toBe(STATE_PALETTE.MOTION);
    expect(r1.pattern).toBe("solid");
    expect(r1.icon).toBe("wave");
    expect(r1.saturation).toBe(1);
    expect(r1.confidenceText).toBe("HIGH 86%");
    expect(r1.subText).toEqual(["Motion last seen 0:42 ago"]);
    const r2 = get(m, "R2");
    expect(r2.label).toBe("NO DETECTION");
    expect(r2.saturation).toBe(0.5);
    expect(r2.confidenceText).toBe("LOW 34%");
    expect(r2.subText).toContain("Still needs a sweep");
  });

  it("off-plan rooms get no polygon and the Not on floor plan chip, after plan rooms", () => {
    const s = store([room("R9"), room("R1")], { ranking: ["R9", "R1"] });
    const m = buildSceneModel(plan, s, NOW_MS, "open");
    expect(m.rooms.map((d) => d.roomId)).toEqual(["R1", "R2", "R3", "R9"]);
    const d = get(m, "R9");
    expect(d.polygon).toBeNull();
    expect(d.effectAnchor).toBeNull();
    expect(d.chips).toContain("Not on floor plan");
    expect(m.priority).toEqual(["R9", "R1"]);
    expect(d.rank).toBe(1);
  });
});

describe("priority, rank, and halo", () => {
  it("filters the server ranking to flagged rooms in server order", () => {
    const s = store(
      [room("R1", { state: "NO_DETECTION" }), room("R2", { state: "POSSIBLE" }), room("R3", { state: "MOTION" })],
      { ranking: ["R3", "R1", "R2"] },
    );
    const m = buildSceneModel(plan, s, NOW_MS, "open");
    expect(m.priority).toEqual(["R3", "R2"]);
    expect(get(m, "R3").rank).toBe(1);
    expect(get(m, "R2").rank).toBe(2);
    expect(get(m, "R1").rank).toBeNull();
    expect(m.rooms.filter((d) => d.halo).map((d) => d.roomId)).toEqual(["R3"]);
    expect(get(m, "R3").ariaLabel).toBe("Office, MOTION, rank 1");
    expect(get(m, "R1").ariaLabel).toBe("Conference, NO DETECTION");
  });

  it("no halo when the rank-1 room is searched; searched rooms are at 35% opacity", () => {
    const s = store([room("R1", { searched: true }), room("R2")], { ranking: ["R1", "R2"] });
    const m = buildSceneModel(plan, s, NOW_MS, "open");
    expect(get(m, "R1").rank).toBe(1);
    expect(get(m, "R1").halo).toBe(false);
    expect(get(m, "R1").opacity).toBe(0.35);
    expect(get(m, "R1").chips).toContain("SEARCHED");
    expect(get(m, "R2").halo).toBe(false);
    expect(get(m, "R2").opacity).toBe(1);
  });

  it("flagged covers MOTION, POSSIBLE, UNKNOWN only", () => {
    expect(["MOTION", "POSSIBLE", "UNKNOWN", "NO_DETECTION", "NONE"].map((t) => flagged(t as never))).toEqual([
      true, true, true, false, false,
    ]);
  });
});

describe("floor tabs, banners, header, snapshot", () => {
  it("counts unsearched flagged rooms per floor and crew from floor_crew_counts", () => {
    const s: StoreState = {
      ...store([room("R1"), room("R2", { searched: true })]),
      crew: { type: "crew", ts: NOW_S, tags: [], floor_crew_counts: { F2: 3 } },
    };
    const m = buildSceneModel(plan, s, NOW_MS, "open");
    // R3 is missing from the message, so it is UNKNOWN (flagged).
    expect(m.floorTabs).toEqual([
      { floorId: "F1", name: "Floor 1", attention: 1, crew: 0 },
      { floorId: "F2", name: "Floor 2", attention: 1, crew: 3 },
    ]);
  });

  it("all-searched banner only when every listed room is searched", () => {
    const rooms = [room("R1", { searched: true }), room("R2", { searched: true }), room("R3", { searched: true })];
    expect(buildSceneModel(plan, store(rooms), NOW_MS, "open").banners.allSearched).toBe(true);
    const some = [room("R1", { searched: true }), room("R2"), room("R3", { searched: true })];
    expect(buildSceneModel(plan, store(some), NOW_MS, "open").banners.allSearched).toBe(false);
    const none = [room("R1", { state: "NO_DETECTION" }), room("R2", { state: "NO_DETECTION" }), room("R3", { state: "NO_DETECTION" })];
    expect(buildSceneModel(plan, store(none), NOW_MS, "open").banners.allSearched).toBe(false);
  });

  it("reconnecting banner follows the link status", () => {
    const s = store([room("R1")]);
    expect(buildSceneModel(plan, s, NOW_MS, "reconnecting").banners.reconnecting).toBe(true);
    expect(buildSceneModel(plan, s, NOW_MS, "open").banners.reconnecting).toBe(false);
  });

  it("header passes recording, health, simulated, and alarm through", () => {
    const s: StoreState = {
      ...store([room("R1")], { simulated: true }),
      recording: { type: "recording", ts: NOW_S, indicator: "Recording (alarm)", stored_samples: 1, fault: null },
      health: { type: "health", ts: NOW_S, summary: "4/4 links OK", nodes: [], tag_faults: [] },
    };
    expect(buildSceneModel(plan, s, NOW_MS, "open").header).toEqual({
      recording: "Recording (alarm)",
      health: "4/4 links OK",
      simulatedData: true,
      alarm: true,
    });
  });

  it("snapshot is alarm_time_state only, unaffected by live state", () => {
    const a = store([room("R1", { alarm_time_state: "MOTION" }), room("R2", { alarm_time_state: null })]);
    const b = store([
      room("R1", { alarm_time_state: "MOTION", state: "NO_DETECTION", searched: true, stale: true }),
      room("R2", { alarm_time_state: null, annotation: "responder_present" }),
    ]);
    const sa = buildSceneModel(plan, a, NOW_MS, "open").snapshot;
    expect(sa).toEqual([
      { roomId: "R1", treatment: "MOTION" },
      { roomId: "R2", treatment: null },
    ]);
    expect(buildSceneModel(plan, b, NOW_MS, "open").snapshot).toEqual(sa);
  });

  it("annotations are label text only and do not change treatment or rank", () => {
    const s = store([room("R1", { annotation: "responder_present" })]);
    const d = get(buildSceneModel(plan, s, NOW_MS, "open"), "R1");
    expect(d.annotations).toEqual(["Motion · responder present"]);
    expect(d.treatment).toBe("MOTION");
    expect(d.rank).toBe(1);
  });
});

describe("purity and anchors", () => {
  it("effectAnchor is the polygon centroid; SIMULATED chip from the plan", () => {
    const m = buildSceneModel(plan, store([room("R1")]), NOW_MS, "open");
    expect(get(m, "R1").effectAnchor).toEqual([2, 1]);
    expect(get(m, "R1").centroid).toEqual([2, 1]);
    expect(get(m, "R3").simulated).toBe(true);
    expect(get(m, "R3").chips).toContain("SIMULATED");
    expect(m.rooms.every((d) => d.crew.length === 0)).toBe(true);
  });

  it("does not mutate inputs and is deterministic", () => {
    const s = store([room("R1"), room("R9")], {}, { lastKnown: { R1: "MOTION" }, lastMessageAt: NOW_MS - 9000 });
    const planCopy = structuredClone(plan);
    const sCopy = structuredClone(s);
    const a = buildSceneModel(plan, s, NOW_MS, "open");
    const b = buildSceneModel(plan, s, NOW_MS, "open");
    expect(a).toEqual(b);
    expect(plan).toEqual(planCopy);
    expect(s).toEqual(sCopy);
  });

  it("no user-visible text contains a banned word", () => {
    const s = store([
      room("R1", { state: "NO_DETECTION" }),
      room("R2", { stale: true, last_known_state: "NO_DETECTION", stale_age_s: 5, calibrated: false }),
      room("R9", { annotation: "recent_motion_may_be_responder" }),
    ]);
    const m = buildSceneModel(plan, s, NOW_MS, "reconnecting");
    const texts = m.rooms.flatMap((d) => [d.name, d.label ?? "", d.ariaLabel, d.confidenceText ?? "", ...d.subText, ...d.chips, ...d.annotations]);
    for (const t of texts) expect(BANNED.test(t)).toBe(false);
  });
});
