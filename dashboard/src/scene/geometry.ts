import type { Door, RoomDef, Vec2 } from '../types';
import { polygonArea } from '../floorplan/validate';

export interface WallSegment {
  a: Vec2;
  b: Vec2;
}

export interface DoorView {
  hinge: Vec2; // where the leaf turns
  latch: Vec2; // the far end of the opening
  inward: Vec2; // unit normal pointing into the room it swings into
  width: number;
}

const EPS = 1e-4;

const sub = (a: Vec2, b: Vec2): Vec2 => [a[0] - b[0], a[1] - b[1]];
const len = (v: Vec2) => Math.hypot(v[0], v[1]);
const lerp = (a: Vec2, b: Vec2, t: number): Vec2 => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];

// Interior is to the left of each edge for a counter-clockwise polygon; flip for clockwise.
function inwardNormal(poly: Vec2[], a: Vec2, b: Vec2): Vec2 {
  const d = sub(b, a);
  const l = len(d) || 1;
  const left: Vec2 = [-d[1] / l, d[0] / l];
  return polygonArea(poly) >= 0 ? left : [-left[0], -left[1]];
}

export function doorViews(room: RoomDef): DoorView[] {
  return (room.doors ?? []).map((d: Door) => {
    const a = room.polygon[d.edge];
    const b = room.polygon[(d.edge + 1) % room.polygon.length];
    const L = len(sub(b, a));
    const near = lerp(a, b, d.offset / L);
    const far = lerp(a, b, (d.offset + d.width) / L);
    // The leaf turns at the near end of the opening unless the plan says "hinge": "end".
    const [hinge, latch] = d.hinge === 'end' ? [far, near] : [near, far];
    let inward = inwardNormal(room.polygon, a, b);
    if (d.swing === 'out') inward = [-inward[0], -inward[1]];
    return { hinge, latch, inward, width: d.width };
  });
}

interface RawEdge {
  a: Vec2;
  b: Vec2;
  gaps: [number, number][]; // in metres from a
}

function sameEdge(e: RawEdge, a: Vec2, b: Vec2): 'same' | 'reversed' | null {
  const near = (p: Vec2, q: Vec2) => Math.abs(p[0] - q[0]) < EPS && Math.abs(p[1] - q[1]) < EPS;
  if (near(e.a, a) && near(e.b, b)) return 'same';
  if (near(e.a, b) && near(e.b, a)) return 'reversed';
  return null;
}

// Every wall on a floor once, with door openings removed. Walls shared by two rooms are merged
// (exact shared edges only) so they don't z-fight in 3D or draw twice as thick in 2D.
export function wallSegments(rooms: RoomDef[]): WallSegment[] {
  const edges: RawEdge[] = [];
  for (const room of rooms) {
    const n = room.polygon.length;
    for (let i = 0; i < n; i++) {
      const a = room.polygon[i];
      const b = room.polygon[(i + 1) % n];
      const L = len(sub(b, a));
      const gaps: [number, number][] = (room.doors ?? [])
        .filter((d) => d.edge === i)
        .map((d) => [d.offset, d.offset + d.width]);
      const existing = edges.find((e) => sameEdge(e, a, b));
      if (!existing) {
        edges.push({ a, b, gaps });
        continue;
      }
      const flip = sameEdge(existing, a, b) === 'reversed';
      for (const [s, e] of gaps) existing.gaps.push(flip ? [L - e, L - s] : [s, e]);
    }
  }

  const out: WallSegment[] = [];
  for (const e of edges) {
    const L = len(sub(e.b, e.a));
    const gaps = [...e.gaps].sort((x, y) => x[0] - y[0]);
    let cursor = 0;
    for (const [s, end] of gaps) {
      if (s - cursor > EPS) out.push({ a: lerp(e.a, e.b, cursor / L), b: lerp(e.a, e.b, s / L) });
      cursor = Math.max(cursor, end);
    }
    if (L - cursor > EPS) out.push({ a: lerp(e.a, e.b, cursor / L), b: e.b });
  }
  return out;
}

export function bounds(polys: Vec2[][]): { minX: number; minY: number; maxX: number; maxY: number } {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const p of polys)
    for (const [x, y] of p) {
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  if (!Number.isFinite(minX)) return { minX: 0, minY: 0, maxX: 1, maxY: 1 };
  return { minX, minY, maxX, maxY };
}

// Distance from a point to the nearest polygon edge: keeps motion rings inside the room.
export function inradiusAt(p: Vec2, poly: Vec2[]): number {
  let best = Infinity;
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i];
    const b = poly[(i + 1) % poly.length];
    const ab = sub(b, a);
    const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / (ab[0] ** 2 + ab[1] ** 2 || 1)));
    best = Math.min(best, len(sub(p, lerp(a, b, t))));
  }
  return best;
}
