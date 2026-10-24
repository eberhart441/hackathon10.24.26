// Floor plan types (Req 6.2). All lengths are meters.
// Node ids and roles are installation data; MAC addresses never appear here.

/** A door on polygon edge `wall` (vertex wall -> vertex (wall+1) % n), starting `offset` m from the edge's first vertex. */
export interface Door {
  wall: number;
  offset: number;
  width: number;
  swing: "in" | "out";
}

/** A furniture block: [x, y, width, depth] in meters, axis aligned. */
export interface Furniture {
  kind: string;
  rect: [x: number, y: number, w: number, d: number];
}

export interface RoomPlan {
  id: string;
  name: string;
  polygon: [number, number][];
  doors: Door[];
  furniture: Furniture[];
  /** Fixed spot where crew markers stack. Not a measured position. */
  crewSlot: [number, number];
  /** Defaults to false. Simulated rooms are labeled SIMULATED on screen. */
  simulated?: boolean;
}

export interface FloorPlanFloor {
  id: string;
  name: string;
  rooms: RoomPlan[];
}

export interface NodePlan {
  id: string;
  role: "TX" | "RX";
  room: string;
  pos: [number, number];
  /** Mounting height in meters. */
  h: number;
}

export interface LinkPlan {
  tx: string;
  rx: string;
}

export interface FloorPlan {
  floors: FloorPlanFloor[];
  nodes: NodePlan[];
  links: LinkPlan[];
}

export type FloorplanRule = "polygon" | "door" | "node_room" | "link" | "duplicate_id" | "schema";

export type FloorplanError = { rule: FloorplanRule; id: string; message: string };

export type FloorplanValidation = { ok: true; plan: FloorPlan } | { ok: false; errors: FloorplanError[] };
