import type {
  CrewMessage,
  HealthMessage,
  HubMessage,
  RecordingMessage,
  RoomStateCode,
  RoomStatesMessage,
  SystemState,
} from './types';

export const HISTORY_S = 300;

/** One room's recent states during the open incident: [epoch seconds, state] samples. */
export type RoomHistory = [number, RoomStateCode][];

// In-memory only. Nothing here is ever written to storage (Kiro R17.3).
export interface StoreState {
  roomStates: RoomStatesMessage | null;
  health: HealthMessage | null;
  crew: CrewMessage | null;
  recording: RecordingMessage | null;
  lastMessageAt: number | null;
  reconnecting: boolean;
  discarded: number;
  history: Record<string, RoomHistory>; // last HISTORY_S seconds per room, incident only
}

export const emptyStore = (): StoreState => ({
  roomStates: null,
  health: null,
  crew: null,
  recording: null,
  lastMessageAt: null,
  reconnecting: false,
  discarded: 0,
  history: {},
});

// Appends at most one sample per room per second, plus every state change, and keeps the last
// HISTORY_S seconds. Outside an incident there is nothing to keep (Kiro R14.4, R17.3).
export function recordHistory(history: Record<string, RoomHistory>, msg: RoomStatesMessage): Record<string, RoomHistory> {
  if (msg.system_state !== 'ALARM_ACTIVE' && msg.system_state !== 'TEST') return {};
  const out: Record<string, RoomHistory> = {};
  for (const r of msg.rooms) {
    const prev = history[r.room_id] ?? [];
    const last = prev[prev.length - 1];
    const state: RoomStateCode = r.stale || !r.calibrated ? 'UNKNOWN' : r.state;
    const keep = prev.filter(([t]) => msg.ts - t <= HISTORY_S);
    if (!last || last[1] !== state || msg.ts - last[0] >= 1) keep.push([msg.ts, state]);
    out[r.room_id] = keep;
  }
  return out;
}

export function systemState(s: StoreState): SystemState {
  return s.roomStates?.system_state ?? 'IDLE';
}

// Pure reducer so the ALARM_ACTIVE -> IDLE purge is testable (Kiro R14.4).
export function applyMessage(s: StoreState, msg: HubMessage, now: number): StoreState {
  const next: StoreState = { ...s, lastMessageAt: now, reconnecting: false };
  switch (msg.type) {
    case 'room_states': {
      const wasAlarm = systemState(s) === 'ALARM_ACTIVE';
      next.roomStates = msg;
      next.history = recordHistory(s.history, msg);
      if (wasAlarm && msg.system_state === 'IDLE') {
        next.roomStates = { ...msg, rooms: [], ranking: [] };
        next.crew = null;
      }
      break;
    }
    case 'health':
      next.health = msg;
      break;
    case 'crew':
      next.crew = msg;
      break;
    case 'recording':
      next.recording = msg;
      break;
  }
  return next;
}

type Listener = (s: StoreState) => void;

export class Store {
  private state: StoreState = emptyStore();
  private listeners = new Set<Listener>();

  get(): StoreState {
    return this.state;
  }

  set(next: StoreState) {
    this.state = next;
    this.listeners.forEach((l) => l(next));
  }

  update(fn: (s: StoreState) => StoreState) {
    this.set(fn(this.state));
  }

  subscribe(l: Listener): () => void {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  }

  reset() {
    this.set(emptyStore());
  }
}
