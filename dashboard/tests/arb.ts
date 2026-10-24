// Shared fast-check arbitraries for hub messages and Store state.
// Every generated message is valid per the parent design's shapes, so
// parseMessage(JSON.stringify(m)) must deep-equal m. Reused by later
// Scene_Model property tests.

import fc from "fast-check";
import { labelFor } from "../src/ws/messages";
import type {
  Annotation,
  Band,
  CrewMsg,
  CrewTag,
  HealthMsg,
  HealthNode,
  HubMessage,
  LinkHealth,
  RecordingMsg,
  RoomEntry,
  RoomStateValue,
  RoomStatesMsg,
  StateLabel,
  SystemState,
  TagFault,
} from "../src/ws/messages";
import type { StoreState } from "../src/store/store";

// ---- enums ----

export const ROOM_STATE_VALUES: readonly RoomStateValue[] = ["MOTION", "POSSIBLE", "UNKNOWN", "NO_DETECTION"];
export const STATE_LABELS: readonly StateLabel[] = ["MOTION", "POSSIBLE", "UNKNOWN", "NO DETECTION"];
export const SYSTEM_STATE_VALUES: readonly SystemState[] = ["IDLE", "CALIBRATION", "TEST", "ALARM_ACTIVE"];

export const arbRoomState: fc.Arbitrary<RoomStateValue> = fc.constantFrom(...ROOM_STATE_VALUES);
export const arbBand: fc.Arbitrary<Band> = fc.constantFrom("high", "medium", "low");
export const arbSystemState: fc.Arbitrary<SystemState> = fc.constantFrom(...SYSTEM_STATE_VALUES);
export const arbLinkHealth: fc.Arbitrary<LinkHealth> = fc.constantFrom("ok", "degraded", "offline");
export const arbAnnotation: fc.Arbitrary<Annotation> = fc.constantFrom(
  null,
  "responder_present" as const,
  "recent_motion_may_be_responder" as const,
);

// ---- primitives ----

/** Epoch seconds (finite, non-negative, so JSON round-trips exactly). */
export const arbEpoch = fc.double({ min: 1.6e9, max: 2e9, noNaN: true });
/** Non-negative finite seconds / counts. */
export const arbSeconds = fc.double({ min: 0, max: 1e6, noNaN: true });
export const arbPct = fc.double({ min: 0, max: 100, noNaN: true });

export const arbRoomId = fc.integer({ min: 1, max: 30 }).map((n) => `R${n}`);
export const arbFloorId = fc.integer({ min: 1, max: 5 }).map((n) => `F${n}`);
export const arbNodeId = fc.tuple(fc.constantFrom("TX", "RX"), fc.integer({ min: 1, max: 30 })).map(([p, n]) => `${p}${n}`);
export const arbTagId = fc.integer({ min: 1, max: 20 }).map((n) => `E${n}`);
export const arbText = fc.string({ maxLength: 40 });

// ---- room_states ----

export const arbRoomEntry: fc.Arbitrary<RoomEntry> = fc
  .record({
    room_id: arbRoomId,
    state: arbRoomState,
    confidence_band: arbBand,
    confidence_pct: arbPct,
    last_seen: fc.option(arbEpoch, { nil: null }),
    last_evidence: fc.option(arbEpoch, { nil: null }),
    stale: fc.boolean(),
    last_known_state: fc.option(arbRoomState, { nil: null }),
    stale_age_s: fc.option(arbSeconds, { nil: null }),
    calibrated: fc.boolean(),
    searched: fc.boolean(),
    annotation: arbAnnotation,
    alarm_time_state: fc.option(arbRoomState, { nil: null }),
    link_health: arbLinkHealth,
    source: fc.constantFrom("edge" as const, "hub" as const),
    model_ver: fc.option(fc.integer({ min: 0, max: 1000 }), { nil: null }),
  })
  // Label is always consistent with state (NO_DETECTION ↔ "NO DETECTION").
  .map((r) => ({ ...r, label: labelFor(r.state) }));

/** room_states with unique room ids and a ranking drawn from those ids. */
export function arbRoomStatesWith(opts: { minRooms?: number; systemState?: fc.Arbitrary<SystemState> } = {}): fc.Arbitrary<RoomStatesMsg> {
  return fc
    .record({
      ts: arbEpoch,
      system_state: opts.systemState ?? arbSystemState,
      simulated: fc.boolean(),
      rooms: fc.uniqueArray(arbRoomEntry, { minLength: opts.minRooms ?? 0, maxLength: 8, selector: (r) => r.room_id }),
    })
    .chain((m) =>
      fc.shuffledSubarray(m.rooms.map((r) => r.room_id)).map((ranking) => ({
        type: "room_states" as const,
        ...m,
        ranking,
      })),
    );
}

export const arbRoomStates: fc.Arbitrary<RoomStatesMsg> = arbRoomStatesWith();

// ---- health ----

export const arbHealthNode: fc.Arbitrary<HealthNode> = fc.record(
  {
    node_id: arbNodeId,
    role: fc.constantFrom("TX" as const, "RX" as const),
    room_id: arbRoomId,
    status: fc.constantFrom("ok" as const, "degraded" as const, "offline" as const, "tx_dead" as const),
    measured_pps: fc.double({ min: 0, max: 1000, noNaN: true }),
    inferred_from: arbNodeId,
    cause: arbText,
    action: arbText,
  },
  { requiredKeys: ["node_id", "role", "room_id", "status"] },
);

export const arbTagFault: fc.Arbitrary<TagFault> = fc.record({
  tag_id: arbTagId,
  last_room: arbRoomId,
  silent_s: arbSeconds,
});

export const arbHealth: fc.Arbitrary<HealthMsg> = fc.record({
  type: fc.constant("health" as const),
  ts: arbEpoch,
  summary: arbText,
  nodes: fc.array(arbHealthNode, { maxLength: 6 }),
  tag_faults: fc.array(arbTagFault, { maxLength: 4 }),
});

// ---- crew ----

export const arbCrewTag: fc.Arbitrary<CrewTag> = fc.record({
  tag_id: arbTagId,
  location_kind: fc.constantFrom("room" as const, "near" as const, "between" as const, "lost" as const),
  room_id: fc.option(arbRoomId, { nil: null }),
  near_rooms: fc.array(arbRoomId, { maxLength: 3 }),
  confidence_band: arbBand,
  last_heard_s: arbSeconds,
  marker: fc.constantFrom("solid" as const, "hollow" as const),
  you_are_here: fc.boolean(),
});

export const arbCrew: fc.Arbitrary<CrewMsg> = fc.record({
  type: fc.constant("crew" as const),
  ts: arbEpoch,
  tags: fc.uniqueArray(arbCrewTag, { maxLength: 6, selector: (t) => t.tag_id }),
  floor_crew_counts: fc.dictionary(arbFloorId, fc.integer({ min: 0, max: 20 }), { maxKeys: 5 }),
});

// ---- recording ----

export const arbRecording: fc.Arbitrary<RecordingMsg> = fc.record({
  type: fc.constant("recording" as const),
  ts: arbEpoch,
  indicator: arbText,
  stored_samples: fc.integer({ min: 0, max: 1_000_000 }),
  fault: fc.option(arbText, { nil: null }),
});

// ---- unions / bundles ----

export const arbHubMessage: fc.Arbitrary<HubMessage> = fc.oneof(arbRoomStates, arbHealth, arbCrew, arbRecording);

export const arbMessageSequence: fc.Arbitrary<HubMessage[]> = fc.array(arbHubMessage, { maxLength: 12 });

/** A StoreState-like bundle: each slot independently present or absent. */
export const arbStoreState: fc.Arbitrary<StoreState> = fc.record({
  roomStates: fc.option(arbRoomStates, { nil: null }),
  health: fc.option(arbHealth, { nil: null }),
  crew: fc.option(arbCrew, { nil: null }),
  recording: fc.option(arbRecording, { nil: null }),
  lastMessageAt: fc.option(fc.integer({ min: 0, max: 2e12 }), { nil: null }),
  lastKnown: fc.dictionary(arbRoomId, fc.constantFrom(...STATE_LABELS), { maxKeys: 8 }),
  discarded: fc.nat({ max: 1000 }),
});
