// Floorplan_Validator (Req 6.3, 6.4). Pure; collects every error and never throws.
import type {
  Door,
  FloorPlan,
  FloorPlanFloor,
  FloorplanError,
  FloorplanRule,
  FloorplanValidation,
  Furniture,
  LinkPlan,
  NodePlan,
  RoomPlan,
} from "./types";

const MIN_AREA_M2 = 0.01;
const EDGE_TOLERANCE_M = 0.001;

type Obj = Record<string, unknown>;

function isObj(v: unknown): v is Obj {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function isPoint(v: unknown): v is [number, number] {
  return Array.isArray(v) && v.length === 2 && isNum(v[0]) && isNum(v[1]);
}

/** Format meters for messages: at most 2 decimals, no trailing zeros. */
function m(v: number): string {
  return `${Number(v.toFixed(2))} m`;
}

/** Shoelace area of a polygon (closing edge implicit). */
export function polygonArea(poly: readonly [number, number][]): number {
  let twice = 0;
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i]!;
    const b = poly[(i + 1) % poly.length]!;
    twice += a[0] * b[1] - b[0] * a[1];
  }
  return Math.abs(twice) / 2;
}

/** Length of polygon edge i (vertex i -> vertex (i+1) % n). */
export function edgeLength(poly: readonly [number, number][], i: number): number {
  const a = poly[i]!;
  const b = poly[(i + 1) % poly.length]!;
  return Math.hypot(b[0] - a[0], b[1] - a[1]);
}

class Collector {
  readonly errors: FloorplanError[] = [];
  add(rule: FloorplanRule, id: string, message: string): void {
    this.errors.push({ rule, id, message });
  }
}

function label(id: string | null, where: string): string {
  return id === null ? where : `"${id}"`;
}

/** Read a string id field, reporting a schema error if missing. Returns null when invalid. */
function readId(o: Obj, kind: string, where: string, c: Collector): string | null {
  const id = o["id"];
  if (typeof id === "string" && id.trim() !== "") return id;
  c.add("schema", where, `${kind} at ${where} needs an "id" text value.`);
  return null;
}

function parseDoor(raw: unknown, roomId: string, idx: number, c: Collector): Door | null {
  const who = `Room "${roomId}": door ${idx}`;
  if (!isObj(raw)) {
    c.add("schema", roomId, `${who} must be an object with wall, offset, width, and swing.`);
    return null;
  }
  let ok = true;
  const { wall, offset, width, swing } = raw;
  if (!isNum(wall) || !Number.isInteger(wall)) {
    c.add("schema", roomId, `${who} needs "wall" as a whole number (the polygon edge index).`);
    ok = false;
  }
  if (!isNum(offset)) {
    c.add("schema", roomId, `${who} needs "offset" as a number of meters.`);
    ok = false;
  }
  if (!isNum(width) || width <= 0) {
    c.add("schema", roomId, `${who} needs "width" as a positive number of meters.`);
    ok = false;
  }
  if (swing !== "in" && swing !== "out") {
    c.add("schema", roomId, `${who} needs "swing" set to "in" or "out".`);
    ok = false;
  }
  if (!ok) return null;
  return { wall: wall as number, offset: offset as number, width: width as number, swing: swing as "in" | "out" };
}

function parseFurniture(raw: unknown, roomId: string, idx: number, c: Collector): Furniture | null {
  const who = `Room "${roomId}": furniture ${idx}`;
  if (!isObj(raw)) {
    c.add("schema", roomId, `${who} must be an object with kind and rect.`);
    return null;
  }
  const { kind, rect } = raw;
  let ok = true;
  if (typeof kind !== "string") {
    c.add("schema", roomId, `${who} needs "kind" as text.`);
    ok = false;
  }
  if (!Array.isArray(rect) || rect.length !== 4 || !rect.every(isNum)) {
    c.add("schema", roomId, `${who} needs "rect" as [x, y, width, depth] in meters.`);
    ok = false;
  }
  if (!ok) return null;
  const r = rect as number[];
  return { kind: kind as string, rect: [r[0]!, r[1]!, r[2]!, r[3]!] };
}

function parseRoom(raw: unknown, where: string, c: Collector): RoomPlan | null {
  if (!isObj(raw)) {
    c.add("schema", where, `Room at ${where} must be an object.`);
    return null;
  }
  const id = readId(raw, "Room", where, c);
  const who = `Room ${label(id, where)}`;
  const rid = id ?? where;
  let ok = id !== null;

  const name = raw["name"];
  if (typeof name !== "string") {
    c.add("schema", rid, `${who} needs a "name" text value.`);
    ok = false;
  }

  const polyRaw = raw["polygon"];
  let polygon: [number, number][] | null = null;
  if (!Array.isArray(polyRaw) || !polyRaw.every(isPoint)) {
    c.add("schema", rid, `${who} needs "polygon" as a list of [x, y] corners in meters.`);
    ok = false;
  } else {
    polygon = polyRaw.map((p) => [p[0], p[1]] as [number, number]);
  }

  const crewSlot = raw["crewSlot"];
  if (!isPoint(crewSlot)) {
    c.add("schema", rid, `${who} needs "crewSlot" as [x, y] in meters.`);
    ok = false;
  }

  const simulated = raw["simulated"];
  if (simulated !== undefined && typeof simulated !== "boolean") {
    c.add("schema", rid, `${who} has "simulated" set to something other than true or false.`);
    ok = false;
  }

  const doorsRaw = raw["doors"];
  const doors: Door[] = [];
  const indexedDoors: { door: Door; i: number }[] = [];
  if (!Array.isArray(doorsRaw)) {
    c.add("schema", rid, `${who} needs "doors" as a list (use [] for none).`);
    ok = false;
  } else {
    doorsRaw.forEach((d, i) => {
      const door = parseDoor(d, rid, i, c);
      if (door) {
        doors.push(door);
        indexedDoors.push({ door, i });
      } else ok = false;
    });
  }

  const furnRaw = raw["furniture"];
  const furniture: Furniture[] = [];
  if (!Array.isArray(furnRaw)) {
    c.add("schema", rid, `${who} needs "furniture" as a list (use [] for none).`);
    ok = false;
  } else {
    furnRaw.forEach((f, i) => {
      const item = parseFurniture(f, rid, i, c);
      if (item) furniture.push(item);
      else ok = false;
    });
  }

  // Geometry rules only make sense once the polygon parsed.
  if (polygon) {
    let polyOk = true;
    if (polygon.length < 3) {
      c.add("polygon", rid, `${who}: polygon needs at least 3 corners (it has ${polygon.length}).`);
      polyOk = false;
    } else {
      const area = polygonArea(polygon);
      if (!(area > MIN_AREA_M2)) {
        c.add(
          "polygon",
          rid,
          `${who}: polygon has no area (${area.toFixed(3)} m²); check that its corners are not all on one line.`,
        );
        polyOk = false;
      }
    }
    if (!polyOk) ok = false;

    if (polygon.length >= 3) {
      const poly = polygon;
      const n = poly.length;
      indexedDoors.forEach(({ door, i }) => {
        if (door.wall < 0 || door.wall >= n) {
          c.add("door", rid, `${who}: door ${i} is on wall ${door.wall}, but the room only has walls 0 to ${n - 1}.`);
          ok = false;
          return;
        }
        if (door.offset < 0) {
          c.add("door", rid, `${who}: door ${i} starts before the beginning of wall ${door.wall} (offset ${m(door.offset)}).`);
          ok = false;
          return;
        }
        const len = edgeLength(poly, door.wall);
        if (door.offset + door.width > len + EDGE_TOLERANCE_M) {
          c.add(
            "door",
            rid,
            `${who}: door ${i} runs past the end of wall ${door.wall} (offset ${m(door.offset)} + width ${m(door.width)} > wall ${m(len)}).`,
          );
          ok = false;
        }
      });
    }
  }

  if (!ok) return null;
  const room: RoomPlan = {
    id: id!,
    name: name as string,
    polygon: polygon!,
    doors,
    furniture,
    crewSlot: [(crewSlot as number[])[0]!, (crewSlot as number[])[1]!],
    simulated: simulated === true,
  };
  return room;
}

function parseFloor(raw: unknown, where: string, c: Collector): FloorPlanFloor | null {
  if (!isObj(raw)) {
    c.add("schema", where, `Floor at ${where} must be an object.`);
    return null;
  }
  const id = readId(raw, "Floor", where, c);
  const who = `Floor ${label(id, where)}`;
  let ok = id !== null;
  const name = raw["name"];
  if (typeof name !== "string") {
    c.add("schema", id ?? where, `${who} needs a "name" text value.`);
    ok = false;
  }
  const roomsRaw = raw["rooms"];
  const rooms: RoomPlan[] = [];
  if (!Array.isArray(roomsRaw)) {
    c.add("schema", id ?? where, `${who} needs "rooms" as a list.`);
    ok = false;
  } else {
    roomsRaw.forEach((r, i) => {
      const room = parseRoom(r, `${where}.rooms[${i}]`, c);
      if (room) rooms.push(room);
      else ok = false;
    });
  }
  if (!ok) return null;
  return { id: id!, name: name as string, rooms };
}

function parseNode(raw: unknown, where: string, c: Collector): NodePlan | null {
  if (!isObj(raw)) {
    c.add("schema", where, `Node at ${where} must be an object.`);
    return null;
  }
  const id = readId(raw, "Node", where, c);
  const who = `Node ${label(id, where)}`;
  const nid = id ?? where;
  let ok = id !== null;
  const { role, room, pos, h } = raw;
  if (role !== "TX" && role !== "RX") {
    c.add("schema", nid, `${who} needs "role" set to "TX" or "RX".`);
    ok = false;
  }
  if (typeof room !== "string") {
    c.add("schema", nid, `${who} needs "room" as a room id.`);
    ok = false;
  }
  if (!isPoint(pos)) {
    c.add("schema", nid, `${who} needs "pos" as [x, y] in meters.`);
    ok = false;
  }
  if (!isNum(h)) {
    c.add("schema", nid, `${who} needs "h" as a mounting height in meters.`);
    ok = false;
  }
  if (!ok) return null;
  const p = pos as number[];
  return { id: id!, role: role as "TX" | "RX", room: room as string, pos: [p[0]!, p[1]!], h: h as number };
}

function parseLink(raw: unknown, where: string, c: Collector): LinkPlan | null {
  if (!isObj(raw) || typeof raw["tx"] !== "string" || typeof raw["rx"] !== "string") {
    c.add("schema", where, `Link at ${where} needs "tx" and "rx" as node ids.`);
    return null;
  }
  return { tx: raw["tx"], rx: raw["rx"] };
}

function reportDuplicates(kind: string, ids: string[], c: Collector): boolean {
  const seen = new Set<string>();
  const reported = new Set<string>();
  for (const id of ids) {
    if (seen.has(id) && !reported.has(id)) {
      c.add("duplicate_id", id, `Duplicate ${kind} id "${id}": each ${kind} id must be unique.`);
      reported.add(id);
    }
    seen.add(id);
  }
  return reported.size === 0;
}

function rawItems(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

/** The string ids of the objects in a raw list, skipping anything malformed. */
function rawIds(v: unknown): string[] {
  return rawItems(v).flatMap((o) => (isObj(o) && typeof o["id"] === "string" && o["id"].trim() !== "" ? [o["id"]] : []));
}

/** Parse an array field of the top-level object. */
function list<T>(
  top: Obj,
  key: string,
  c: Collector,
  parse: (raw: unknown, where: string, c: Collector) => T | null,
): { items: T[]; ok: boolean } {
  const raw = top[key];
  if (!Array.isArray(raw)) {
    c.add("schema", key, `The floor plan needs "${key}" as a list.`);
    return { items: [], ok: false };
  }
  const items: T[] = [];
  let ok = true;
  raw.forEach((r, i) => {
    const item = parse(r, `${key}[${i}]`, c);
    if (item) items.push(item);
    else ok = false;
  });
  return { items, ok };
}

export function validateFloorplan(input: unknown): FloorplanValidation {
  const c = new Collector();
  try {
    if (!isObj(input)) {
      c.add("schema", "floorplan", "The floor plan must be a JSON object with floors, nodes, and links.");
      return { ok: false, errors: c.errors };
    }
    const floors = list(input, "floors", c, parseFloor);
    const nodes = list(input, "nodes", c, parseNode);
    const links = list(input, "links", c, parseLink);

    // Ids come from the raw input, so a room that failed another rule still
    // counts for uniqueness and for node references (no cascading errors).
    const rawFloors = rawItems(input["floors"]);
    const rawRoomIds = rawFloors.flatMap((f) => rawIds(isObj(f) ? f["rooms"] : undefined));
    reportDuplicates("floor", rawIds(input["floors"]), c);
    reportDuplicates("room", rawRoomIds, c);
    reportDuplicates("node", rawIds(input["nodes"]), c);

    const roomIds = new Set(rawRoomIds);
    for (const n of nodes.items) {
      if (!roomIds.has(n.room)) {
        c.add("node_room", n.id, `Node "${n.id}": room "${n.room}" does not exist on any floor.`);
      }
    }

    const nodeById = new Map(nodes.items.map((n) => [n.id, n] as const));
    for (const l of links.items) {
      const lid = `${l.tx}→${l.rx}`;
      const who = `Link ${l.tx} → ${l.rx}`;
      const tx = nodeById.get(l.tx);
      const rx = nodeById.get(l.rx);
      if (!tx) c.add("link", lid, `${who}: TX node "${l.tx}" does not exist.`);
      else if (tx.role !== "TX") c.add("link", lid, `${who}: node "${l.tx}" is an ${tx.role} node, but a link must start at a TX node.`);
      if (!rx) c.add("link", lid, `${who}: RX node "${l.rx}" does not exist.`);
      else if (rx.role !== "RX") c.add("link", lid, `${who}: node "${l.rx}" is a ${rx.role} node, but a link must end at an RX node.`);
    }

    if (c.errors.length > 0 || !floors.ok || !nodes.ok || !links.ok) {
      return { ok: false, errors: c.errors };
    }
    const plan: FloorPlan = { floors: floors.items, nodes: nodes.items, links: links.items };
    return { ok: true, plan };
  } catch (e) {
    // Defensive: the validator must never throw.
    c.add("schema", "floorplan", `The floor plan could not be checked: ${e instanceof Error ? e.message : String(e)}`);
    return { ok: false, errors: c.errors };
  }
}
