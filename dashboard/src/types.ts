// Wire types for the hub WebSocket and REST API.
// Shapes follow the parent design, "Hub: Web Server" section.

export type RoomStateCode = 'MOTION' | 'POSSIBLE' | 'NO_DETECTION' | 'UNKNOWN';
export type SystemState = 'IDLE' | 'CALIBRATION' | 'TEST' | 'ALARM_ACTIVE';
export type Band = 'high' | 'medium' | 'low';
export type LinkHealthStage = 'ok' | 'degraded' | 'offline';

export interface RoomStateMsg {
  room_id: string;
  state: RoomStateCode;
  label?: string;
  confidence_band: Band;
  confidence_pct: number;
  last_seen: number | null;
  last_evidence?: number | null;
  stale: boolean;
  last_known_state: RoomStateCode | null;
  stale_age_s: number | null;
  calibrated: boolean;
  searched: boolean;
  annotation: string | null;
  alarm_time_state: RoomStateCode | null;
  link_health: string;
  source?: 'edge' | 'hub';
  model_ver?: number | null;
  // Extra ML classification of the room's receivers (hub/ml_classifier.py). Shown under the
  // normal text only; it never changes the room state.
  ml?: { label: string; motion_pct: number } | null;
}

export interface RoomStatesMessage {
  type: 'room_states';
  ts: number;
  system_state: SystemState;
  simulated: boolean;
  rooms: RoomStateMsg[];
  ranking: string[];
}

export interface HealthNode {
  node_id: string;
  role: 'RX' | 'TX' | string;
  room_id: string;
  status: string; // ok | degraded | offline | tx_dead | recovering
  measured_pps?: number;
  inferred_from?: string;
  cause?: string;
  action?: string;
}

export interface TagFault {
  tag_id: string;
  last_room: string | null;
  silent_s: number;
}

export interface HealthMessage {
  type: 'health';
  ts: number;
  summary: string;
  nodes: HealthNode[];
  tag_faults: TagFault[];
}

export interface CrewTag {
  tag_id: string;
  location_kind: 'room' | 'near' | 'between' | 'lost';
  room_id: string | null;
  near_rooms: string[];
  confidence_band: Band;
  last_heard_s: number;
  marker: 'solid' | 'hollow';
  you_are_here?: boolean;
}

export interface CrewMessage {
  type: 'crew';
  ts: number;
  tags: CrewTag[];
  floor_crew_counts: Record<string, number>;
}

export interface RecordingMessage {
  type: 'recording';
  ts: number;
  indicator: string;
  stored_samples: number;
  fault: string | null;
}

export type HubMessage = RoomStatesMessage | HealthMessage | CrewMessage | RecordingMessage;

// Floor plan file (hub/config/floorplan.json). Lengths in meters.
export type Vec2 = [number, number];

export interface Door {
  edge: number;
  offset: number;
  width: number;
  swing?: 'in' | 'out';
  hinge?: 'start' | 'end'; // which end of the opening the leaf turns on (default start)
}

export interface Furniture {
  kind: string;
  x: number;
  y: number;
  w: number;
  d: number;
  h?: number;
}

export interface RoomDef {
  id: string;
  name: string;
  simulated?: boolean;
  polygon: Vec2[];
  doors: Door[];
  furniture: Furniture[];
  crewSlot: Vec2;
}

export interface FloorDef {
  id: string;
  name: string;
  level?: number;
  rooms: RoomDef[];
}

export interface NodeDef {
  id: string;
  role: 'TX' | 'RX';
  room: string;
  pos: Vec2;
  h: number;
}

export interface LinkDef {
  tx: string;
  rx: string;
}

export interface Floorplan {
  floors: FloorDef[];
  nodes: NodeDef[];
  links: LinkDef[];
}
