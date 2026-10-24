import type { Floorplan, RoomDef, Vec2 } from '../types';

export type ValidationResult = { ok: true; plan: Floorplan } | { ok: false; errors: string[] };

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const isVec = (v: unknown): v is Vec2 => Array.isArray(v) && v.length === 2 && isNum(v[0]) && isNum(v[1]);

export function polygonArea(poly: Vec2[]): number {
  let a = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i];
    const [x2, y2] = poly[(i + 1) % poly.length];
    a += x1 * y2 - x2 * y1;
  }
  return a / 2;
}

export function edgeLength(poly: Vec2[], edge: number): number {
  const a = poly[edge];
  const b = poly[(edge + 1) % poly.length];
  return Math.hypot(b[0] - a[0], b[1] - a[1]);
}

// Checks the hand-edited floor plan and explains every problem in plain language (Kiro R6.3, R6.4).
export function validateFloorplan(input: unknown): ValidationResult {
  const errors: string[] = [];
  const o = input as Partial<Floorplan> | null;
  if (!o || typeof o !== 'object' || !Array.isArray(o.floors) || o.floors.length === 0) {
    return { ok: false, errors: ['The floor plan has no "floors" list.'] };
  }

  const floorIds = new Set<string>();
  const roomIds = new Set<string>();
  for (const f of o.floors) {
    if (!f || typeof f.id !== 'string') {
      errors.push('A floor is missing its "id".');
      continue;
    }
    if (floorIds.has(f.id)) errors.push(`Floor id "${f.id}" is used more than once.`);
    floorIds.add(f.id);
    if (!Array.isArray(f.rooms)) {
      errors.push(`Floor "${f.id}" has no "rooms" list.`);
      continue;
    }
    for (const r of f.rooms as RoomDef[]) checkRoom(r, f.id, roomIds, errors);
    const walls = (f as { walls?: unknown }).walls;
    if (walls !== undefined && !(Array.isArray(walls) && walls.every((l) => Array.isArray(l) && l.length >= 3 && l.every(isVec)))) {
      errors.push(`Floor "${f.id}" has a "walls" entry that is not a list of loops of at least 3 [x, y] points.`);
    }
  }

  const nodeIds = new Set<string>();
  const nodeRole = new Map<string, string>();
  for (const n of o.nodes ?? []) {
    if (!n || typeof n.id !== 'string') {
      errors.push('A node is missing its "id".');
      continue;
    }
    if (nodeIds.has(n.id)) errors.push(`Node id "${n.id}" is used more than once.`);
    nodeIds.add(n.id);
    nodeRole.set(n.id, n.role);
    if (n.role !== 'TX' && n.role !== 'RX') errors.push(`Node "${n.id}" has role "${n.role}"; it must be TX or RX.`);
    if (!roomIds.has(n.room)) errors.push(`Node "${n.id}" points to room "${n.room}", which is not on the floor plan.`);
    if (!isVec(n.pos) || !isNum(n.h)) errors.push(`Node "${n.id}" needs "pos" [x, y] and "h" in meters.`);
  }

  for (const l of o.links ?? []) {
    if (nodeRole.get(l.tx) !== 'TX') errors.push(`Link ${l.tx} → ${l.rx}: "${l.tx}" is not an existing TX node.`);
    if (nodeRole.get(l.rx) !== 'RX') errors.push(`Link ${l.tx} → ${l.rx}: "${l.rx}" is not an existing RX node.`);
  }

  if (errors.length) return { ok: false, errors };
  return {
    ok: true,
    plan: { floors: o.floors, nodes: o.nodes ?? [], links: o.links ?? [] } as Floorplan,
  };
}

function checkRoom(r: RoomDef, floorId: string, roomIds: Set<string>, errors: string[]) {
  if (!r || typeof r.id !== 'string') {
    errors.push(`A room on floor "${floorId}" is missing its "id".`);
    return;
  }
  if (roomIds.has(r.id)) errors.push(`Room id "${r.id}" is used more than once.`);
  roomIds.add(r.id);
  if (typeof r.name !== 'string' || !r.name) errors.push(`Room "${r.id}" needs a "name".`);

  if (!Array.isArray(r.polygon) || r.polygon.length < 3 || !r.polygon.every(isVec)) {
    errors.push(`Room "${r.id}" needs a "polygon" of at least 3 [x, y] points.`);
    return;
  }
  if (Math.abs(polygonArea(r.polygon)) < 1e-6) errors.push(`Room "${r.id}" has a polygon with zero area.`);

  for (const [i, d] of (r.doors ?? []).entries()) {
    if (!Number.isInteger(d.edge) || d.edge < 0 || d.edge >= r.polygon.length) {
      errors.push(`Room "${r.id}" door ${i + 1} is on edge ${d.edge}, but the polygon has edges 0 to ${r.polygon.length - 1}.`);
      continue;
    }
    if (d.swing !== undefined && d.swing !== 'in' && d.swing !== 'out' && d.swing !== 'none') {
      errors.push(`Room "${r.id}" door ${i + 1} has swing "${d.swing}"; it must be in, out or none.`);
    }
    const len = edgeLength(r.polygon, d.edge);
    if (!isNum(d.offset) || !isNum(d.width) || d.offset < 0 || d.width <= 0 || d.offset + d.width > len + 1e-6) {
      errors.push(
        `Room "${r.id}" door ${i + 1} does not fit its wall: offset ${d.offset} m + width ${d.width} m is longer than the ${len.toFixed(2)} m wall.`,
      );
    }
  }
  if (!isVec(r.crewSlot)) errors.push(`Room "${r.id}" needs a "crewSlot" [x, y].`);
}
