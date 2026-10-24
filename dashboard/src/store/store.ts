// In-memory Store (Req 7.2, 7.6, 14.4, 17.3).
// A module-level variable plus a subscriber list. No persistence adapter:
// nothing here touches Web Storage, IndexedDB, or the Cache API.

import { labelFor } from "../ws/messages";
import type {
  CrewMsg,
  HealthMsg,
  HubMessage,
  RecordingMsg,
  RoomEntry,
  RoomStatesMsg,
  StateLabel,
} from "../ws/messages";

export interface StoreState {
  roomStates: RoomStatesMsg | null;
  health: HealthMsg | null;
  crew: CrewMsg | null;
  recording: RecordingMsg | null;
  lastMessageAt: number | null; // ms, receipt time
  lastKnown: Record<string, StateLabel>; // last label per room, for hub-lost text
  discarded: number;
}

export function initialState(): StoreState {
  return {
    roomStates: null,
    health: null,
    crew: null,
    recording: null,
    lastMessageAt: null,
    lastKnown: {},
    discarded: 0,
  };
}

/** Label of the treatment the user saw for this room entry. */
function displayedLabel(r: RoomEntry, prev: StateLabel | undefined): StateLabel {
  if (!r.stale) return r.label;
  if (r.last_known_state !== null) return labelFor(r.last_known_state);
  return prev ?? "UNKNOWN";
}

function isIdle(s: StoreState): boolean {
  return s.roomStates?.system_state === "IDLE";
}

function purgeCrew(c: CrewMsg | null): CrewMsg | null {
  return c === null ? null : { ...c, tags: [] };
}

/** Pure reducer: returns a new state, never mutates `s` or `m`. */
export function reduce(s: StoreState, m: HubMessage, receivedAt: number): StoreState {
  const base: StoreState = { ...s, lastMessageAt: receivedAt };
  switch (m.type) {
    case "room_states": {
      if (m.system_state === "IDLE") {
        // Defence in depth (Req 14.2, 14.4): drop room and crew entries.
        return {
          ...base,
          roomStates: { ...m, rooms: [], ranking: [] },
          crew: purgeCrew(s.crew),
          lastKnown: {},
        };
      }
      const lastKnown: Record<string, StateLabel> = { ...s.lastKnown };
      for (const r of m.rooms) lastKnown[r.room_id] = displayedLabel(r, s.lastKnown[r.room_id]);
      return { ...base, roomStates: m, lastKnown };
    }
    case "crew":
      // While IDLE, keep no crew tag entries even if the hub sends some.
      return { ...base, crew: isIdle(s) ? purgeCrew(m) : m };
    case "health":
      return { ...base, health: m };
    case "recording":
      return { ...base, recording: m };
  }
}

/** Pure reducer for a frame that failed to parse (Req 7.2): count and drop. */
export function discard(s: StoreState): StoreState {
  return { ...s, discarded: s.discarded + 1 };
}

// ---- module-level store ----

type Listener = (s: StoreState) => void;

let state: StoreState = initialState();
const listeners = new Set<Listener>();

export function getState(): StoreState {
  return state;
}

function set(next: StoreState): void {
  state = next;
  for (const fn of [...listeners]) fn(state);
}

/** Applies a parsed message, or counts a discard when `m` is null. */
export function dispatch(m: HubMessage | null, receivedAt: number): void {
  set(m === null ? discard(state) : reduce(state, m, receivedAt));
}

export function subscribe(fn: Listener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/** Test helper: restores the initial state and drops all subscribers. */
export function resetStore(): void {
  state = initialState();
  listeners.clear();
}
