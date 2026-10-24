// Scene_Model: the one pure view model both renderers draw (Req 8, 9, 11, 12,
// 13.5, 14.2, 16.5, 19.2). A pure function of the floor plan, the Store, the
// current time, and the socket status: no Date.now, no DOM, no input mutation.
// The hub is the source of truth; nothing here recomputes state, confidence,
// or rank order.

import type { FloorPlan, RoomPlan } from "../floorplan/types";
import type { StoreState } from "../store/store";
import type { Band, CrewMsg, RoomEntry, RoomStateValue, StateLabel } from "../ws/messages";
import { labelFor } from "../ws/messages";
import { formatAge } from "./format";
import { centroid } from "./geometry";
import { CREW_PALETTE, SATURATION_BY_BAND, STATE_PALETTE } from "./palette";
import type { IconId, PatternId } from "./patterns";
import { TREATMENTS } from "./patterns";
import { STRINGS } from "./strings";

/** Hub-lost threshold: 5 s with no message (Req 12.2). */
export const HUB_LOST_MS = 5000;

export type LinkStatus = "connecting" | "open" | "reconnecting";
export type Treatment = RoomStateValue | "NONE";
export type Chip =
  | typeof STRINGS.searched
  | typeof STRINGS.simulated
  | typeof STRINGS.uncalibrated
  | typeof STRINGS.notOnFloorPlan;

export interface CrewItem {
  tagId: string;
  kind: "marker" | "chip";
  hollow: boolean;
  roomId: string | null; // only for kind "marker"
  text: string;
  colors: [typeof CREW_PALETTE[0], typeof CREW_PALETTE[1]];
}

export interface RoomDescriptor {
  roomId: string;
  floorId: string | null;
  name: string;
  polygon: [number, number][] | null;
  centroid: [number, number] | null;
  treatment: Treatment; // "NONE" only in IDLE
  label: StateLabel | null;
  icon: IconId | null;
  pattern: PatternId | null;
  fill: string | null;
  saturation: 1 | 0.75 | 0.5;
  opacity: 1 | 0.35;
  greyed: boolean;
  rank: number | null;
  halo: boolean;
  confidenceText: string | null; // "HIGH 86%"
  subText: string[];
  chips: Chip[];
  annotations: string[]; // label text only
  crew: CrewItem[];
  simulated: boolean;
  searched: boolean;
  ariaLabel: string; // "<name>, <label>, rank <n>"
  effectAnchor: [number, number] | null; // always the centroid
}

export interface SceneModel {
  mode: "idle" | "fire";
  rooms: RoomDescriptor[]; // floor-plan rooms, then off-plan rooms
  priority: string[]; // room ids, server order, flagged only
  snapshot: { roomId: string; treatment: RoomStateValue | null }[];
  floorTabs: { floorId: string; name: string; attention: number; crew: number }[];
  banners: { hubLost: boolean; allSearched: boolean; reconnecting: boolean };
  header: { recording: string | null; health: string | null; simulatedData: boolean; alarm: boolean };
}

// ---- small exported helpers (reused by property tests) ----

/** Flagged treatments: MOTION, POSSIBLE, UNKNOWN (Req 8.2). */
export function flagged(t: Treatment): t is "MOTION" | "POSSIBLE" | "UNKNOWN" {
  return t === "MOTION" || t === "POSSIBLE" || t === "UNKNOWN";
}

/** Fire-mode treatment for a room entry: steps 4–6 of the rule table. */
export function treatmentForEntry(r: RoomEntry): RoomStateValue {
  if (r.stale || !r.calibrated) return "UNKNOWN";
  return r.state;
}

/** True when the hub has been silent for at least 5 s (Req 12.2). No message yet is not hub loss. */
export function isHubLost(lastMessageAt: number | null, nowMs: number): boolean {
  return lastMessageAt !== null && nowMs - lastMessageAt >= HUB_LOST_MS;
}

const BAND_TEXT: Readonly<Record<Band, string>> = {
  high: STRINGS.bandHigh,
  medium: STRINGS.bandMedium,
  low: STRINGS.bandLow,
};

/** "HIGH 86%" (Req 9.7). */
export function confidenceText(band: Band, pct: number): string {
  return `${BAND_TEXT[band]} ${Math.round(pct)}%`;
}

/** "Motion last seen 0:42 ago", or "Motion last seen never" (Req 12.5). `lastSeen` is epoch seconds. */
export function motionText(lastSeen: number | null, nowMs: number): string {
  if (lastSeen === null) return `${STRINGS.motionLastSeen} ${STRINGS.never}`;
  return `${STRINGS.motionLastSeen} ${formatAge(nowMs / 1000 - lastSeen)} ${STRINGS.ago}`;
}

/** "last known POSSIBLE, 0:40 ago" (Req 12.1). */
export function staleText(lastKnown: RoomStateValue | null, staleAgeS: number | null): string {
  const label = lastKnown === null ? STRINGS.labelUnknown : labelFor(lastKnown);
  return `${STRINGS.lastKnown} ${label}, ${formatAge(staleAgeS ?? 0)} ${STRINGS.ago}`;
}

/** "STALE — last known MOTION, 0:07 ago" (Req 12.3). Ages in ms. */
export function hubLostText(label: StateLabel, sinceMs: number): string {
  return `${STRINGS.stale} — ${STRINGS.lastKnown} ${label}, ${formatAge(sinceMs / 1000)} ${STRINGS.ago}`;
}

/** "<name>, <label>, rank <n>" (Req 19.2); parts that do not apply are left out. */
export function ariaLabelFor(name: string, label: StateLabel | null, rank: number | null): string {
  const parts = [name];
  if (label !== null) parts.push(label);
  if (rank !== null) parts.push(`${STRINGS.rank} ${rank}`);
  return parts.join(", ");
}

const ANNOTATION_TEXT: Readonly<Record<NonNullable<RoomEntry["annotation"]>, string>> = {
  responder_present: STRINGS.responderPresent,
  recent_motion_may_be_responder: STRINGS.recentMotionMayBeResponder,
};

/**
 * Crew hook (Req 15). Returns the crew items to show for one room.
 * Crew rules arrive in task 11.4; until then no crew item is drawn.
 */
export function crewItemsForRoom(_roomId: string, _crew: CrewMsg | null, _nowMs: number): CrewItem[] {
  return [];
}

// ---- builder ----

interface Slot {
  roomId: string;
  floorId: string | null;
  plan: RoomPlan | null;
  entry: RoomEntry | null;
}

function firstById(rooms: readonly RoomEntry[]): Map<string, RoomEntry> {
  const out = new Map<string, RoomEntry>();
  for (const r of rooms) if (!out.has(r.room_id)) out.set(r.room_id, r);
  return out;
}

function describe(
  slot: Slot,
  fire: boolean,
  hubLost: boolean,
  s: StoreState,
  nowMs: number,
): Omit<RoomDescriptor, "rank" | "halo" | "ariaLabel"> {
  const { plan, entry } = slot;
  const polygon = plan ? plan.polygon.map(([x, y]) => [x, y] as [number, number]) : null;
  const c = polygon ? centroid(polygon) : null;
  const simulated = plan?.simulated === true;
  const chips: Chip[] = [];
  const subText: string[] = [];
  const annotations: string[] = [];

  // Step 2 (composes on top of 3–6): hub lost greys every room.
  if (hubLost && fire && s.lastMessageAt !== null) {
    const known = s.lastKnown[slot.roomId];
    if (known !== undefined) subText.push(hubLostText(known, nowMs - s.lastMessageAt));
  }

  let treatment: Treatment = "NONE";
  let saturation: 1 | 0.75 | 0.5 = 1;
  let confidence: string | null = null;
  let searched = false;

  if (fire) {
    if (entry === null) {
      // Step 3: plan room missing from the message.
      treatment = "UNKNOWN";
      subText.push(STRINGS.noDataFromHub);
    } else {
      treatment = treatmentForEntry(entry);
      saturation = SATURATION_BY_BAND[entry.confidence_band];
      confidence = confidenceText(entry.confidence_band, entry.confidence_pct);
      searched = entry.searched;
      if (entry.stale) {
        // Step 4.
        subText.push(staleText(entry.last_known_state, entry.stale_age_s));
      } else {
        // Step 6 (also applies to uncalibrated, non-stale rooms).
        if (treatment === "NO_DETECTION") subText.push(STRINGS.stillNeedsSweep);
        subText.push(motionText(entry.last_seen, nowMs));
      }
      // Step 5.
      if (!entry.calibrated) chips.push(STRINGS.uncalibrated);
      if (entry.annotation !== null) annotations.push(ANNOTATION_TEXT[entry.annotation]);
    }
  }

  if (searched) chips.push(STRINGS.searched);
  if (simulated) chips.push(STRINGS.simulated);
  if (plan === null) chips.push(STRINGS.notOnFloorPlan);

  const enc = treatment === "NONE" ? null : TREATMENTS[treatment];
  return {
    roomId: slot.roomId,
    floorId: slot.floorId,
    name: plan?.name ?? slot.roomId,
    polygon,
    centroid: c,
    treatment,
    label: enc?.label ?? null,
    icon: enc?.icon ?? null,
    pattern: enc?.pattern ?? null,
    fill: treatment === "NONE" ? null : STATE_PALETTE[treatment],
    saturation,
    opacity: searched ? 0.35 : 1,
    greyed: hubLost,
    confidenceText: confidence,
    subText,
    chips,
    annotations,
    crew: fire ? crewItemsForRoom(slot.roomId, s.crew, nowMs) : [],
    simulated,
    searched,
    effectAnchor: c,
  };
}

export function buildSceneModel(plan: FloorPlan, s: StoreState, nowMs: number, link: LinkStatus): SceneModel {
  const msg = s.roomStates;
  // Step 1: IDLE (or nothing yet) shows no occupancy, even if entries arrived (Req 14.2).
  const fire = msg !== null && msg.system_state !== "IDLE";
  const entries = fire ? firstById(msg.rooms) : new Map<string, RoomEntry>();
  const hubLost = isHubLost(s.lastMessageAt, nowMs);

  const planIds = new Set<string>();
  const slots: Slot[] = [];
  for (const floor of plan.floors) {
    for (const room of floor.rooms) {
      planIds.add(room.id);
      slots.push({ roomId: room.id, floorId: floor.id, plan: room, entry: entries.get(room.id) ?? null });
    }
  }
  for (const [id, entry] of entries) {
    if (!planIds.has(id)) slots.push({ roomId: id, floorId: null, plan: null, entry });
  }

  const base = slots.map((slot) => describe(slot, fire, hubLost, s, nowMs));
  const byId = new Map(base.map((d) => [d.roomId, d] as const));

  // Priority = server ranking filtered to flagged treatments; no other ordering (Req 8.2).
  const priority: string[] = [];
  if (fire) {
    const seen = new Set<string>();
    for (const id of msg.ranking) {
      if (seen.has(id)) continue;
      seen.add(id);
      const d = byId.get(id);
      if (d !== undefined && flagged(d.treatment)) priority.push(id);
    }
  }
  const rankOf = new Map(priority.map((id, i) => [id, i + 1] as const));
  const top = priority[0];

  const rooms: RoomDescriptor[] = base.map((d) => {
    const rank = rankOf.get(d.roomId) ?? null;
    return {
      ...d,
      rank,
      halo: d.roomId === top && !d.searched,
      ariaLabel: ariaLabelFor(d.name, d.label, rank),
    };
  });

  const floorTabs = plan.floors.map((f) => {
    const counts = s.crew?.floor_crew_counts;
    const crew = counts !== undefined && Object.prototype.hasOwnProperty.call(counts, f.id) ? (counts[f.id] ?? 0) : 0;
    return {
      floorId: f.id,
      name: f.name,
      attention: rooms.filter((d) => d.floorId === f.id && !d.searched && flagged(d.treatment)).length,
      crew,
    };
  });

  const snapshot = fire ? [...entries.values()].map((r) => ({ roomId: r.room_id, treatment: r.alarm_time_state })) : [];

  return {
    mode: fire ? "fire" : "idle",
    rooms,
    priority,
    snapshot,
    floorTabs,
    banners: {
      hubLost,
      allSearched: priority.length > 0 && priority.every((id) => byId.get(id)?.searched === true),
      reconnecting: link === "reconnecting",
    },
    header: {
      recording: s.recording?.indicator ?? null,
      health: s.health?.summary ?? null,
      simulatedData: msg?.simulated === true,
      alarm: msg?.system_state === "ALARM_ACTIVE",
    },
  };
}
