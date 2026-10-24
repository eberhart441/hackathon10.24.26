import type { CrewTag, Floorplan, RoomDef, RoomStateCode, RoomStateMsg, Vec2 } from '../types';
import type { StoreState } from '../store';
import { ageText } from './format';
import {
  BAND_SATURATION,
  GREY_FILL,
  STATE_FILL,
  STATE_LABEL,
  STATE_PATTERN,
  desaturate,
  type PatternId,
} from './palette';

export const HUB_LOST_MS = 5000;

const FLAGGED: ReadonlySet<RoomStateCode> = new Set(['MOTION', 'POSSIBLE', 'UNKNOWN']);
const OCCUPANCY_STATES = new Set(['ALARM_ACTIVE', 'TEST']);

const ANNOTATION_TEXT: Record<string, string> = {
  responder_present: 'Motion · responder present',
  recent_motion_may_be_responder: 'recent motion may be responder',
};

export interface Occupancy {
  state: RoomStateCode;
  label: string;
  pattern: PatternId;
  fill: string;
  confText: string;
  detailText: string | null; // "Motion last seen 0:42 ago" or the stale text
  mlText: string | null; // "ML: motion 87%", the extra ML classification line
  subLabel: string | null;
  stale: boolean;
  searched: boolean;
  uncalibrated: boolean;
  annotation: string | null;
  alarmTimeLabel: string | null;
  alarmTimeState: RoomStateCode | null;
  linkHealth: string;
  source: string | null;
  rank: number | null;
  isTop: boolean;
}

export interface CrewItem {
  tagId: string;
  hollow: boolean;
  text: string;
}

export interface RoomDescriptor {
  id: string;
  name: string;
  floorId: string;
  def: RoomDef;
  centroid: Vec2;
  simulated: boolean;
  greyed: boolean; // hub lost
  occupancy: Occupancy | null; // null outside an incident: draw architecture only
  crew: CrewItem[];
  ariaLabel: string;
}

export interface ListItem {
  roomId: string;
  name: string;
  rank: number;
  isTop: boolean;
  state: RoomStateCode;
  label: string;
  confText: string;
  detailText: string | null;
  searched: boolean;
  simulated: boolean;
  onPlan: boolean;
  note: string | null;
  floorId: string | null;
}

export interface CrewChip {
  tagId: string;
  text: string;
  rooms: string[];
  floorId: string | null;
}

export interface NodeView {
  id: string;
  role: string;
  status: string;
}

export interface FloorView {
  id: string;
  name: string;
  attention: number;
  crew: number;
}

export interface SceneModel {
  occupancyShown: boolean;
  alarm: boolean;
  hubLost: boolean;
  hubLostAgeText: string | null;
  simulated: boolean;
  rooms: RoomDescriptor[];
  list: ListItem[];
  ordered: RoomDescriptor[]; // every plan room, in the hub's ranking order (unranked rooms last)
  allSearched: boolean;
  floors: FloorView[];
  crewChips: CrewChip[];
  nodes: Record<string, NodeView>;
}

export function centroid(poly: Vec2[]): Vec2 {
  let a = 0;
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i];
    const [x2, y2] = poly[(i + 1) % poly.length];
    const f = x1 * y2 - x2 * y1;
    a += f;
    cx += (x1 + x2) * f;
    cy += (y1 + y2) * f;
  }
  if (Math.abs(a) < 1e-9) return poly[0];
  return [cx / (3 * a), cy / (3 * a)];
}

// Pure: same floor plan + store + time always gives the same picture (Kiro R8.6).
export function buildSceneModel(plan: Floorplan, store: StoreState, now: number): SceneModel {
  const rs = store.roomStates;
  const occupancyShown = !!rs && OCCUPANCY_STATES.has(rs.system_state);
  const alarm = rs?.system_state === 'ALARM_ACTIVE';
  const hubLost = store.lastMessageAt === null || now - store.lastMessageAt >= HUB_LOST_MS;
  const sinceMsg = store.lastMessageAt === null ? null : (now - store.lastMessageAt) / 1000;
  const nowS = now / 1000;

  const msgById = new Map<string, RoomStateMsg>();
  if (occupancyShown) for (const r of rs!.rooms) msgById.set(r.room_id, r);

  const roomDefs = new Map<string, { def: RoomDef; floorId: string }>();
  for (const f of plan.floors) for (const r of f.rooms) roomDefs.set(r.id, { def: r, floorId: f.id });

  // Priority list: flagged rooms in server ranking order, never re-sorted (Kiro R8.2).
  const list: ListItem[] = [];
  if (occupancyShown) {
    const seen = new Set<string>();
    for (const id of rs!.ranking) {
      const m = msgById.get(id);
      if (!m || seen.has(id) || !FLAGGED.has(m.state)) continue;
      seen.add(id);
      const where = roomDefs.get(id);
      const rank = list.length + 1;
      list.push({
        roomId: id,
        name: where?.def.name ?? id,
        rank,
        isTop: false,
        state: m.state,
        label: STATE_LABEL[m.state],
        confText: confText(m),
        detailText: detailText(m, nowS, hubLost, sinceMsg),
        searched: m.searched,
        simulated: !!where?.def.simulated,
        onPlan: !!where,
        note: where ? null : 'Not on floor plan',
        floorId: where?.floorId ?? null,
      });
    }
    // Halo goes to the first room still waiting for a search.
    if (list.length && !list[0].searched) list[0].isTop = true;
  }
  const rankById = new Map(list.map((l) => [l.roomId, l]));

  const crewByRoom = new Map<string, CrewItem[]>();
  const crewChips: CrewChip[] = [];
  if (occupancyShown && store.crew) {
    for (const t of store.crew.tags) placeCrew(t, roomDefs, crewByRoom, crewChips);
  }

  const rooms: RoomDescriptor[] = [];
  for (const [id, { def, floorId }] of roomDefs) {
    let occupancy: Occupancy | null = null;
    if (occupancyShown) {
      const m = msgById.get(id);
      occupancy = m ? occupancyFor(m, nowS, hubLost, sinceMsg, rankById.get(id)) : noDataOccupancy();
    }
    const crew = crewByRoom.get(id) ?? [];
    rooms.push({
      id,
      name: def.name,
      floorId,
      def,
      centroid: centroid(def.polygon),
      simulated: !!def.simulated,
      greyed: hubLost && occupancyShown,
      occupancy,
      crew,
      ariaLabel: ariaFor(def, occupancy),
    });
  }

  const floors: FloorView[] = plan.floors.map((f) => ({
    id: f.id,
    name: f.name,
    attention: list.filter((l) => l.floorId === f.id && !l.searched).length,
    crew: occupancyShown ? store.crew?.floor_crew_counts[f.id] ?? 0 : 0,
  }));

  const nodes: Record<string, NodeView> = {};
  for (const n of plan.nodes) nodes[n.id] = { id: n.id, role: n.role, status: 'unknown' };
  for (const n of store.health?.nodes ?? []) {
    if (nodes[n.node_id]) nodes[n.node_id].status = hubLost ? 'unknown' : n.status;
  }

  return {
    occupancyShown,
    alarm,
    hubLost,
    hubLostAgeText: sinceMsg === null ? null : ageText(sinceMsg),
    simulated: !!rs?.simulated,
    rooms,
    list,
    ordered: orderByRanking(rooms, occupancyShown ? rs!.ranking : []),
    allSearched: list.length > 0 && list.every((l) => l.searched),
    floors,
    crewChips,
    nodes,
  };
}

// Server order is the only order (Kiro R8.2); rooms the hub did not rank keep plan order after it.
function orderByRanking(rooms: RoomDescriptor[], ranking: string[]): RoomDescriptor[] {
  const pos = new Map(ranking.map((id, i) => [id, i]));
  return rooms
    .map((r, i) => ({ r, key: pos.get(r.id) ?? ranking.length + i }))
    .sort((a, b) => a.key - b.key)
    .map((x) => x.r);
}

function confText(m: RoomStateMsg): string {
  return `${m.confidence_band.toUpperCase()} ${Math.round(m.confidence_pct)}%`;
}

function mlText(ml: { label: string; motion_pct: number }): string {
  return ml.label === 'motion' ? `ML: motion ${Math.round(ml.motion_pct)}%` : `ML: no motion ${100 - Math.round(ml.motion_pct)}%`;
}

function detailText(m: RoomStateMsg, nowS: number, hubLost: boolean, sinceMsg: number | null): string | null {
  if (hubLost) {
    const lk = m.state;
    return `STALE — last known ${STATE_LABEL[lk]}${sinceMsg !== null ? `, ${ageText(sinceMsg)} ago` : ''}`;
  }
  if (m.stale) {
    const lk = m.last_known_state;
    if (!lk) return 'No recent data';
    return `last known ${STATE_LABEL[lk]}, ${ageText(m.stale_age_s ?? 0)} ago`;
  }
  if (m.last_seen !== null) return `Motion last seen ${ageText(nowS - m.last_seen)} ago`;
  return null;
}

function occupancyFor(
  m: RoomStateMsg,
  nowS: number,
  hubLost: boolean,
  sinceMsg: number | null,
  item: ListItem | undefined,
): Occupancy {
  // Stale or uncalibrated rooms always get the UNKNOWN treatment (Kiro R9.8, R12.1).
  const shown: RoomStateCode = m.stale || !m.calibrated ? 'UNKNOWN' : m.state;
  const fill = hubLost ? GREY_FILL : desaturate(STATE_FILL[shown], BAND_SATURATION[m.confidence_band]);
  return {
    state: shown,
    label: STATE_LABEL[shown],
    pattern: STATE_PATTERN[shown],
    fill,
    confText: confText(m),
    detailText: detailText(m, nowS, hubLost, sinceMsg),
    mlText: hubLost || !m.ml ? null : mlText(m.ml),
    subLabel: shown === 'NO_DETECTION' ? 'Still needs a sweep' : null,
    stale: m.stale || hubLost,
    searched: m.searched,
    uncalibrated: !m.calibrated,
    annotation: m.annotation ? ANNOTATION_TEXT[m.annotation] ?? null : null,
    alarmTimeLabel: m.alarm_time_state ? STATE_LABEL[m.alarm_time_state] : null,
    alarmTimeState: m.alarm_time_state,
    linkHealth: m.link_health,
    source: m.source ? (m.source === 'edge' ? 'Edge' : 'Hub') : null,
    rank: item?.rank ?? null,
    isTop: item?.isTop ?? false,
  };
}

// A room on the plan that the hub said nothing about during an incident (Kiro R8.4).
function noDataOccupancy(): Occupancy {
  return {
    state: 'UNKNOWN',
    label: STATE_LABEL.UNKNOWN,
    pattern: STATE_PATTERN.UNKNOWN,
    fill: STATE_FILL.UNKNOWN,
    confText: 'LOW 0%',
    detailText: 'No data from hub',
    mlText: null,
    subLabel: null,
    stale: true,
    searched: false,
    uncalibrated: false,
    annotation: null,
    alarmTimeLabel: null,
    alarmTimeState: null,
    linkHealth: 'offline',
    source: null,
    rank: null,
    isTop: false,
  };
}

function placeCrew(
  t: CrewTag,
  roomDefs: Map<string, { def: RoomDef; floorId: string }>,
  byRoom: Map<string, CrewItem[]>,
  chips: CrewChip[],
) {
  const add = (roomId: string, item: CrewItem) => {
    if (!roomDefs.has(roomId)) return;
    byRoom.set(roomId, [...(byRoom.get(roomId) ?? []), item]);
  };
  const nameOf = (id: string) => roomDefs.get(id)?.def.name ?? id;
  const floorOf = (ids: string[]) => ids.map((id) => roomDefs.get(id)?.floorId).find(Boolean) ?? null;

  if (t.marker === 'hollow' || t.location_kind === 'lost') {
    // Shown where it was last heard; never extrapolated (parent R25.7).
    if (t.room_id) add(t.room_id, { tagId: t.tag_id, hollow: true, text: `Last heard ${nameOf(t.room_id)}, ${ageText(t.last_heard_s)} ago` });
    else chips.push({ tagId: t.tag_id, text: `${t.tag_id} · not heard for ${ageText(t.last_heard_s)}`, rooms: [], floorId: null });
    return;
  }
  if (t.location_kind === 'room' && t.room_id && t.confidence_band !== 'low') {
    add(t.room_id, { tagId: t.tag_id, hollow: false, text: `${t.tag_id} · heard ${ageText(t.last_heard_s)} ago` });
    return;
  }
  // Low confidence never resolves to a single room (Kiro R15.2, R15.3, R15.5).
  const rooms = t.near_rooms.length ? t.near_rooms : t.room_id ? [t.room_id] : [];
  const text =
    t.location_kind === 'between' || rooms.length < 2
      ? `${t.tag_id} · Between rooms`
      : `${t.tag_id} · Near ${nameOf(rooms[0])} / ${nameOf(rooms[1])}`;
  chips.push({ tagId: t.tag_id, text, rooms, floorId: floorOf(rooms) });
}

function ariaFor(def: RoomDef, o: Occupancy | null): string {
  if (!o) return `${def.name}`;
  const parts = [def.name, o.label, o.confText];
  if (o.rank) parts.unshift(`Priority ${o.rank}`);
  if (o.searched) parts.push('searched');
  if (o.detailText) parts.push(o.detailText);
  return parts.join(', ');
}
