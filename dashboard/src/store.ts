import type { CrewMessage, HealthMessage, HubMessage, RecordingMessage, RoomStatesMessage, SystemState } from './types';

// In-memory only. Nothing here is ever written to storage (Kiro R17.3).
export interface StoreState {
  roomStates: RoomStatesMessage | null;
  health: HealthMessage | null;
  crew: CrewMessage | null;
  recording: RecordingMessage | null;
  lastMessageAt: number | null;
  reconnecting: boolean;
  discarded: number;
}

export const emptyStore = (): StoreState => ({
  roomStates: null,
  health: null,
  crew: null,
  recording: null,
  lastMessageAt: null,
  reconnecting: false,
  discarded: 0,
});

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
