// Typed hub → dashboard WebSocket messages (Req 7.1, 7.2).
// Shapes mirror the parent design's "Hub: Web Server" section exactly.
// No runtime dependencies. parseMessage never throws; null means "discard".

export type RoomStateValue = "MOTION" | "POSSIBLE" | "UNKNOWN" | "NO_DETECTION";
export type StateLabel = "MOTION" | "POSSIBLE" | "UNKNOWN" | "NO DETECTION";
export type Band = "high" | "medium" | "low";
export type SystemState = "IDLE" | "CALIBRATION" | "TEST" | "ALARM_ACTIVE";
export type LinkHealth = "ok" | "degraded" | "offline";
export type Annotation = "responder_present" | "recent_motion_may_be_responder" | null;

export interface RoomEntry {
  room_id: string;
  state: RoomStateValue;
  label: StateLabel;
  confidence_band: Band;
  confidence_pct: number; // 0..100
  last_seen: number | null; // epoch seconds
  last_evidence: number | null; // epoch seconds
  stale: boolean;
  last_known_state: RoomStateValue | null;
  stale_age_s: number | null;
  calibrated: boolean;
  searched: boolean;
  annotation: Annotation;
  alarm_time_state: RoomStateValue | null;
  link_health: LinkHealth;
  source: "edge" | "hub";
  model_ver: number | null;
}

export interface RoomStatesMsg {
  type: "room_states";
  ts: number;
  system_state: SystemState;
  simulated: boolean;
  rooms: RoomEntry[];
  ranking: string[];
}

export interface HealthNode {
  node_id: string;
  role: "TX" | "RX";
  room_id: string;
  status: "ok" | "degraded" | "offline" | "tx_dead";
  measured_pps?: number;
  inferred_from?: string;
  cause?: string;
  action?: string;
}

export interface TagFault {
  tag_id: string;
  last_room: string;
  silent_s: number;
}

export interface HealthMsg {
  type: "health";
  ts: number;
  summary: string;
  nodes: HealthNode[];
  tag_faults: TagFault[];
}

export interface CrewTag {
  tag_id: string;
  location_kind: "room" | "near" | "between" | "lost";
  room_id: string | null;
  near_rooms: string[];
  confidence_band: Band;
  last_heard_s: number;
  marker: "solid" | "hollow";
  you_are_here: boolean;
}

export interface CrewMsg {
  type: "crew";
  ts: number;
  tags: CrewTag[];
  floor_crew_counts: Record<string, number>;
}

export interface RecordingMsg {
  type: "recording";
  ts: number;
  indicator: string;
  stored_samples: number;
  fault: string | null;
}

export type HubMessage = RoomStatesMsg | HealthMsg | CrewMsg | RecordingMsg;

const ROOM_STATES: readonly RoomStateValue[] = ["MOTION", "POSSIBLE", "UNKNOWN", "NO_DETECTION"];
const BANDS: readonly Band[] = ["high", "medium", "low"];
const SYSTEM_STATES: readonly SystemState[] = ["IDLE", "CALIBRATION", "TEST", "ALARM_ACTIVE"];
const LINK_HEALTH: readonly LinkHealth[] = ["ok", "degraded", "offline"];
const ANNOTATIONS: readonly Exclude<Annotation, null>[] = ["responder_present", "recent_motion_may_be_responder"];
const SOURCES: readonly RoomEntry["source"][] = ["edge", "hub"];
const ROLES: readonly HealthNode["role"][] = ["TX", "RX"];
const NODE_STATUSES: readonly HealthNode["status"][] = ["ok", "degraded", "offline", "tx_dead"];
const LOCATION_KINDS: readonly CrewTag["location_kind"][] = ["room", "near", "between", "lost"];
const MARKERS: readonly CrewTag["marker"][] = ["solid", "hollow"];

/** Display label for a room state: NO_DETECTION ↔ "NO DETECTION", others unchanged. */
export function labelFor(state: RoomStateValue): StateLabel {
  return state === "NO_DETECTION" ? "NO DETECTION" : state;
}

// Thrown internally only; parseMessage catches it and returns null.
class Invalid extends Error {}

type Obj = Record<string, unknown>;

function fail(): never {
  throw new Invalid();
}

function obj(v: unknown): Obj {
  if (typeof v !== "object" || v === null || Array.isArray(v)) fail();
  return v as Obj;
}

function str(v: unknown): string {
  if (typeof v !== "string") fail();
  return v;
}

function num(v: unknown): number {
  if (typeof v !== "number" || !Number.isFinite(v)) fail();
  return v;
}

function bool(v: unknown): boolean {
  if (typeof v !== "boolean") fail();
  return v;
}

function oneOf<T extends string>(v: unknown, allowed: readonly T[]): T {
  if (typeof v !== "string" || !(allowed as readonly string[]).includes(v)) fail();
  return v as T;
}

function nullable<T>(v: unknown, f: (x: unknown) => T): T | null {
  return v === null ? null : f(v);
}

function optional<T>(o: Obj, key: string, f: (x: unknown) => T): T | undefined {
  return Object.prototype.hasOwnProperty.call(o, key) ? f(o[key]) : undefined;
}

/** Reads a required own property; a missing key is a parse failure. */
function req(o: Obj, key: string): unknown {
  if (!Object.prototype.hasOwnProperty.call(o, key)) fail();
  return o[key];
}

function arr<T>(v: unknown, f: (x: unknown) => T): T[] {
  if (!Array.isArray(v)) fail();
  return v.map(f);
}

function roomEntry(v: unknown): RoomEntry {
  const o = obj(v);
  const state = oneOf(req(o, "state"), ROOM_STATES);
  const label = str(req(o, "label"));
  if (label !== labelFor(state)) fail();
  const pct = num(req(o, "confidence_pct"));
  if (pct < 0 || pct > 100) fail();
  return {
    room_id: str(req(o, "room_id")),
    state,
    label: labelFor(state),
    confidence_band: oneOf(req(o, "confidence_band"), BANDS),
    confidence_pct: pct,
    last_seen: nullable(req(o, "last_seen"), num),
    last_evidence: nullable(req(o, "last_evidence"), num),
    stale: bool(req(o, "stale")),
    last_known_state: nullable(req(o, "last_known_state"), (x) => oneOf(x, ROOM_STATES)),
    stale_age_s: nullable(req(o, "stale_age_s"), num),
    calibrated: bool(req(o, "calibrated")),
    searched: bool(req(o, "searched")),
    annotation: nullable(req(o, "annotation"), (x) => oneOf(x, ANNOTATIONS)),
    alarm_time_state: nullable(req(o, "alarm_time_state"), (x) => oneOf(x, ROOM_STATES)),
    link_health: oneOf(req(o, "link_health"), LINK_HEALTH),
    source: oneOf(req(o, "source"), SOURCES),
    model_ver: nullable(req(o, "model_ver"), num),
  };
}

function healthNode(v: unknown): HealthNode {
  const o = obj(v);
  const node: HealthNode = {
    node_id: str(req(o, "node_id")),
    role: oneOf(req(o, "role"), ROLES),
    room_id: str(req(o, "room_id")),
    status: oneOf(req(o, "status"), NODE_STATUSES),
  };
  const measured = optional(o, "measured_pps", num);
  const inferred = optional(o, "inferred_from", str);
  const cause = optional(o, "cause", str);
  const action = optional(o, "action", str);
  if (measured !== undefined) node.measured_pps = measured;
  if (inferred !== undefined) node.inferred_from = inferred;
  if (cause !== undefined) node.cause = cause;
  if (action !== undefined) node.action = action;
  return node;
}

function tagFault(v: unknown): TagFault {
  const o = obj(v);
  return {
    tag_id: str(req(o, "tag_id")),
    last_room: str(req(o, "last_room")),
    silent_s: num(req(o, "silent_s")),
  };
}

function crewTag(v: unknown): CrewTag {
  const o = obj(v);
  return {
    tag_id: str(req(o, "tag_id")),
    location_kind: oneOf(req(o, "location_kind"), LOCATION_KINDS),
    room_id: nullable(req(o, "room_id"), str),
    near_rooms: arr(req(o, "near_rooms"), str),
    confidence_band: oneOf(req(o, "confidence_band"), BANDS),
    last_heard_s: num(req(o, "last_heard_s")),
    marker: oneOf(req(o, "marker"), MARKERS),
    you_are_here: bool(req(o, "you_are_here")),
  };
}

function counts(v: unknown): Record<string, number> {
  const o = obj(v);
  const out: Record<string, number> = {};
  for (const [k, n] of Object.entries(o)) out[k] = num(n);
  return out;
}

function decode(o: Obj): HubMessage {
  const ts = num(req(o, "ts"));
  switch (req(o, "type")) {
    case "room_states":
      return {
        type: "room_states",
        ts,
        system_state: oneOf(req(o, "system_state"), SYSTEM_STATES),
        simulated: bool(req(o, "simulated")),
        rooms: arr(req(o, "rooms"), roomEntry),
        ranking: arr(req(o, "ranking"), str),
      };
    case "health":
      return {
        type: "health",
        ts,
        summary: str(req(o, "summary")),
        nodes: arr(req(o, "nodes"), healthNode),
        tag_faults: arr(req(o, "tag_faults"), tagFault),
      };
    case "crew":
      return {
        type: "crew",
        ts,
        tags: arr(req(o, "tags"), crewTag),
        floor_crew_counts: counts(req(o, "floor_crew_counts")),
      };
    case "recording":
      return {
        type: "recording",
        ts,
        indicator: str(req(o, "indicator")),
        stored_samples: num(req(o, "stored_samples")),
        fault: nullable(req(o, "fault"), str),
      };
    default:
      return fail();
  }
}

/**
 * Parses one hub WebSocket frame. Returns null on any mismatch in field
 * names, types, or enum values (caller discards and counts it, Req 7.2).
 * Never throws. Unknown extra fields are dropped from the result.
 */
export function parseMessage(raw: string): HubMessage | null {
  try {
    return decode(obj(JSON.parse(raw)));
  } catch {
    return null;
  }
}
