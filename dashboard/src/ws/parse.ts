import type {
  CrewMessage,
  HealthMessage,
  HubMessage,
  RecordingMessage,
  RoomStateCode,
  RoomStatesMessage,
} from '../types';

// Hand-written guards: a message that fails is discarded and counted (Kiro R7.2).

const STATES: readonly string[] = ['MOTION', 'POSSIBLE', 'NO_DETECTION', 'UNKNOWN'];
const SYSTEM: readonly string[] = ['IDLE', 'CALIBRATION', 'TEST', 'ALARM_ACTIVE'];
const BANDS: readonly string[] = ['high', 'medium', 'low'];

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === 'string';
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const isNumOrNull = (v: unknown) => v === null || v === undefined || isNum(v);
const isStateOrNull = (v: unknown) => v === null || v === undefined || (isStr(v) && STATES.includes(v));

function roomOk(r: unknown): boolean {
  return (
    isObj(r) &&
    isStr(r.room_id) &&
    isStr(r.state) &&
    STATES.includes(r.state) &&
    isStr(r.confidence_band) &&
    BANDS.includes(r.confidence_band) &&
    isNum(r.confidence_pct) &&
    r.confidence_pct >= 0 &&
    r.confidence_pct <= 100 &&
    isNumOrNull(r.last_seen) &&
    typeof r.stale === 'boolean' &&
    isStateOrNull(r.last_known_state) &&
    isNumOrNull(r.stale_age_s) &&
    typeof r.calibrated === 'boolean' &&
    typeof r.searched === 'boolean' &&
    isStateOrNull(r.alarm_time_state)
  );
}

function roomStates(m: Record<string, unknown>): RoomStatesMessage | null {
  if (!isStr(m.system_state) || !SYSTEM.includes(m.system_state)) return null;
  if (typeof m.simulated !== 'boolean' || !Array.isArray(m.rooms) || !Array.isArray(m.ranking)) return null;
  if (!m.rooms.every(roomOk) || !m.ranking.every(isStr)) return null;
  const rooms = (m.rooms as Record<string, unknown>[]).map((r) => ({
    ...r,
    last_known_state: (r.last_known_state ?? null) as RoomStateCode | null,
    alarm_time_state: (r.alarm_time_state ?? null) as RoomStateCode | null,
    stale_age_s: (r.stale_age_s ?? null) as number | null,
    last_seen: (r.last_seen ?? null) as number | null,
    annotation: (r.annotation ?? null) as string | null,
    link_health: isStr(r.link_health) ? r.link_health : 'ok',
  }));
  return { ...(m as unknown as RoomStatesMessage), rooms: rooms as unknown as RoomStatesMessage['rooms'] };
}

function health(m: Record<string, unknown>): HealthMessage | null {
  if (!isStr(m.summary) || !Array.isArray(m.nodes)) return null;
  const nodesOk = m.nodes.every((n) => isObj(n) && isStr(n.node_id) && isStr(n.status));
  if (!nodesOk) return null;
  const tagFaults = Array.isArray(m.tag_faults) ? m.tag_faults : [];
  if (!tagFaults.every((t) => isObj(t) && isStr(t.tag_id) && isNum(t.silent_s))) return null;
  return { ...(m as unknown as HealthMessage), tag_faults: tagFaults as HealthMessage['tag_faults'] };
}

function crew(m: Record<string, unknown>): CrewMessage | null {
  if (!Array.isArray(m.tags)) return null;
  const kinds = ['room', 'near', 'between', 'lost'];
  const ok = m.tags.every(
    (t) =>
      isObj(t) &&
      isStr(t.tag_id) &&
      isStr(t.location_kind) &&
      kinds.includes(t.location_kind) &&
      isStr(t.confidence_band) &&
      BANDS.includes(t.confidence_band) &&
      isNum(t.last_heard_s) &&
      (t.marker === 'solid' || t.marker === 'hollow'),
  );
  if (!ok) return null;
  const tags = (m.tags as Record<string, unknown>[]).map((t) => ({
    ...t,
    room_id: isStr(t.room_id) ? t.room_id : null,
    near_rooms: Array.isArray(t.near_rooms) ? t.near_rooms.filter(isStr) : [],
  }));
  const counts = isObj(m.floor_crew_counts) ? m.floor_crew_counts : {};
  return { ...(m as unknown as CrewMessage), tags: tags as unknown as CrewMessage['tags'], floor_crew_counts: counts as Record<string, number> };
}

function recording(m: Record<string, unknown>): RecordingMessage | null {
  if (!isStr(m.indicator) || !isNum(m.stored_samples)) return null;
  return { ...(m as unknown as RecordingMessage), fault: isStr(m.fault) ? m.fault : null };
}

export function parseMessage(raw: unknown): HubMessage | null {
  let m: unknown = raw;
  if (typeof raw === 'string') {
    try {
      m = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (!isObj(m) || !isNum(m.ts)) return null;
  switch (m.type) {
    case 'room_states':
      return roomStates(m);
    case 'health':
      return health(m);
    case 'crew':
      return crew(m);
    case 'recording':
      return recording(m);
    default:
      return null;
  }
}
