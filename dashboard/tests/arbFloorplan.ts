// fast-check arbitraries for floor plans (Property 16, Req 6.3, 6.4).
// arbFloorplan builds plans that satisfy every validator rule by construction.
// arbBrokenFloorplan(rule) takes a valid plan and breaks exactly that one rule,
// reporting the id the validator must name.
import fc from "fast-check";
import type { Door, FloorPlan, FloorPlanFloor, FloorplanRule, Furniture, LinkPlan, NodePlan, RoomPlan } from "../src/floorplan/types";
import { edgeLength } from "../src/floorplan/validate";

type Pt = [number, number];

/** Finite double in [min, max]; `+ 0` turns -0 into 0 so JSON round trips are exact. */
const num = (min: number, max: number): fc.Arbitrary<number> =>
  fc.double({ min, max, noNaN: true, noDefaultInfinity: true }).map((v) => v + 0);

const point = (lim = 20): fc.Arbitrary<Pt> => fc.tuple(num(-lim, lim), num(-lim, lim));

/** Axis-aligned rectangle, sides 0.5 to 10 m. */
const arbRect: fc.Arbitrary<Pt[]> = fc
  .record({ x: num(-20, 20), y: num(-20, 20), w: num(0.5, 10), h: num(0.5, 10) })
  .map(({ x, y, w, h }) => [
    [x, y],
    [x + w, y],
    [x + w, y + h],
    [x, y + h],
  ]);

/** Regular convex polygon, 3 to 8 corners, radius 0.5 to 5 m (area >= 0.32 m²). */
const arbConvex: fc.Arbitrary<Pt[]> = fc
  .record({ c: point(), r: num(0.5, 5), n: fc.integer({ min: 3, max: 8 }), rot: num(0, 2 * Math.PI) })
  .map(({ c, r, n, rot }) =>
    Array.from({ length: n }, (_, i): Pt => {
      const a = rot + (2 * Math.PI * i) / n;
      return [c[0] + r * Math.cos(a) + 0, c[1] + r * Math.sin(a) + 0];
    }),
  );

export const arbPolygon: fc.Arbitrary<Pt[]> = fc.oneof(arbRect, arbConvex);

/** A door that fits on one edge of `poly`. */
export function arbDoor(poly: Pt[]): fc.Arbitrary<Door> {
  return fc
    .record({
      wall: fc.integer({ min: 0, max: poly.length - 1 }),
      wf: num(0.05, 1),
      of: num(0, 1),
      swing: fc.constantFrom("in" as const, "out" as const),
    })
    .map(({ wall, wf, of, swing }) => {
      const len = edgeLength(poly, wall);
      const width = len * wf;
      return { wall, offset: (len - width) * of + 0, width, swing };
    });
}

const arbFurniture: fc.Arbitrary<Furniture> = fc.record({
  kind: fc.string({ maxLength: 8 }),
  rect: fc.tuple(num(-20, 20), num(-20, 20), num(0, 5), num(0, 5)),
});

type RoomBody = Omit<RoomPlan, "id">;

const arbRoomBody: fc.Arbitrary<RoomBody> = arbPolygon.chain((polygon) =>
  fc
    .record({
      name: fc.string({ maxLength: 10 }),
      doors: fc.array(arbDoor(polygon), { maxLength: 3 }),
      furniture: fc.array(arbFurniture, { maxLength: 2 }),
      crewSlot: point(),
      simulated: fc.boolean(),
    })
    .map((r) => ({ ...r, polygon })),
);

/** Id tag: arbitrary text appended to an index prefix, so ids stay unique per kind. */
const tag = fc.string({ maxLength: 4 });

const arbFloors: fc.Arbitrary<FloorPlanFloor[]> = fc
  .array(
    fc.record({
      name: fc.string({ maxLength: 10 }),
      tag,
      rooms: fc.array(fc.tuple(arbRoomBody, tag), { minLength: 1, maxLength: 3 }),
    }),
    { minLength: 1, maxLength: 3 },
  )
  .map((floors) => {
    let r = 0;
    return floors.map((f, fi) => ({
      id: `F${fi}-${f.tag}`,
      name: f.name,
      rooms: f.rooms.map(([body, t]) => ({ id: `R${r++}-${t}`, ...body })),
    }));
  });

/** A valid floor plan: positive-area polygons, fitting doors, nodes in real rooms, TX→RX links, unique ids. */
export const arbFloorplan: fc.Arbitrary<FloorPlan> = arbFloors.chain((floors) => {
  const roomIds = floors.flatMap((f) => f.rooms.map((r) => r.id));
  return fc
    .array(
      fc.record({
        role: fc.constantFrom("TX" as const, "RX" as const),
        room: fc.constantFrom(...roomIds),
        pos: point(),
        h: num(0, 3),
        tag,
      }),
      { maxLength: 6 },
    )
    .map((ns): NodePlan[] => ns.map(({ tag: t, ...n }, i) => ({ id: `N${i}-${t}`, ...n })))
    .chain((nodes) => {
      const txs = nodes.filter((n) => n.role === "TX").map((n) => n.id);
      const rxs = nodes.filter((n) => n.role === "RX").map((n) => n.id);
      const links: fc.Arbitrary<LinkPlan[]> =
        txs.length > 0 && rxs.length > 0
          ? fc.array(fc.record({ tx: fc.constantFrom(...txs), rx: fc.constantFrom(...rxs) }), { maxLength: 4 })
          : fc.constant<LinkPlan[]>([]);
      return links.map((l): FloorPlan => ({ floors, nodes, links: l }));
    });
});

export type BrokenRule = Exclude<FloorplanRule, "schema">;
export interface Broken {
  plan: FloorPlan;
  rule: BrokenRule;
  /** The id the validator must report for the broken item. */
  id: string;
}

function roomLocs(plan: FloorPlan): [number, number][] {
  return plan.floors.flatMap((f, fi) => f.rooms.map((_, ri): [number, number] => [fi, ri]));
}

function roomAt(plan: FloorPlan, [fi, ri]: [number, number]): RoomPlan {
  return plan.floors[fi]!.rooms[ri]!;
}

/** Polygon under 3 corners, or zero area (all corners on one line). Doors are cleared so only the polygon rule fires. */
function breakPolygon(plan: FloorPlan): fc.Arbitrary<Broken> {
  const tooFew = fc.array(point(), { maxLength: 2 });
  const collinear = fc
    .record({ p: point(), d: fc.tuple(num(-2, 2), num(-2, 2)), k: fc.integer({ min: 3, max: 6 }) })
    .map(({ p, d, k }) => Array.from({ length: k }, (_, t): Pt => [p[0] + t * d[0] + 0, p[1] + t * d[1] + 0]));
  return fc.record({ loc: fc.constantFrom(...roomLocs(plan)), poly: fc.oneof(tooFew, collinear) }).map(({ loc, poly }) => {
    const p = structuredClone(plan);
    const room = roomAt(p, loc);
    room.polygon = poly;
    room.doors = [];
    return { plan: p, rule: "polygon", id: room.id };
  });
}

/** Add a door that runs past its wall's end, starts before it, or sits on a wall that does not exist. */
function breakDoor(plan: FloorPlan): fc.Arbitrary<Broken> {
  return fc
    .record({
      loc: fc.constantFrom(...roomLocs(plan)),
      kind: fc.constantFrom("past", "negative", "wall"),
      wallPick: fc.nat(),
      width: num(0.05, 2),
      excess: num(0.01, 5),
      swing: fc.constantFrom("in" as const, "out" as const),
    })
    .map(({ loc, kind, wallPick, width, excess, swing }) => {
      const p = structuredClone(plan);
      const room = roomAt(p, loc);
      const n = room.polygon.length;
      let door: Door;
      if (kind === "wall") {
        const wall = wallPick % 2 === 0 ? n + (wallPick % 5) : -1 - (wallPick % 5);
        door = { wall, offset: 0, width, swing };
      } else {
        const wall = wallPick % n;
        const len = edgeLength(room.polygon, wall);
        const offset = kind === "past" ? len - width + excess : -excess;
        door = { wall, offset, width, swing };
      }
      room.doors.push(door);
      return { plan: p, rule: "door", id: room.id };
    });
}

/** Point an existing node (or a new one) at a room id that is on no floor. */
function breakNodeRoom(plan: FloorPlan): fc.Arbitrary<Broken> {
  return fc
    .record({ pick: fc.nat(), addNew: fc.boolean(), t: tag, pos: point(), h: num(0, 3), role: fc.constantFrom("TX" as const, "RX" as const) })
    .map(({ pick, addNew, t, pos, h, role }) => {
      const p = structuredClone(plan);
      const missing = `missing-room-${t}`;
      if (addNew || p.nodes.length === 0) {
        const id = `N${p.nodes.length}-new`;
        p.nodes.push({ id, role, room: missing, pos, h });
        return { plan: p, rule: "node_room", id };
      }
      const node = p.nodes[pick % p.nodes.length]!;
      node.room = missing;
      return { plan: p, rule: "node_room", id: node.id };
    });
}

/** Add a link whose TX or RX node is missing or has the wrong role. */
function breakLink(plan: FloorPlan): fc.Arbitrary<Broken> {
  const txs = plan.nodes.filter((n) => n.role === "TX").map((n) => n.id);
  const rxs = plan.nodes.filter((n) => n.role === "RX").map((n) => n.id);
  const ghostTx = fc.constant("ghost-tx");
  const ghostRx = fc.constant("ghost-rx");
  const anyEnd = fc.constantFrom("ghost-any", ...txs, ...rxs);
  const variants: fc.Arbitrary<{ tx: string; rx: string }>[] = [
    fc.record({ tx: ghostTx, rx: rxs.length > 0 ? fc.constantFrom(...rxs) : ghostRx }),
    fc.record({ tx: txs.length > 0 ? fc.constantFrom(...txs) : ghostTx, rx: ghostRx }),
  ];
  if (rxs.length > 0) variants.push(fc.record({ tx: fc.constantFrom(...rxs), rx: anyEnd }));
  if (txs.length > 0) variants.push(fc.record({ tx: anyEnd, rx: fc.constantFrom(...txs) }));
  return fc.oneof(...variants).map((link) => {
    const p = structuredClone(plan);
    p.links.push(link);
    return { plan: p, rule: "link", id: `${link.tx}→${link.rx}` };
  });
}

/** Repeat a room id (copy of a room on any floor), a floor id (empty copy), or a node id (copy of a node). */
function breakDuplicateId(plan: FloorPlan): fc.Arbitrary<Broken> {
  const kinds = plan.nodes.length > 0 ? (["room", "floor", "node"] as const) : (["room", "floor"] as const);
  return fc
    .record({ kind: fc.constantFrom(...kinds), loc: fc.constantFrom(...roomLocs(plan)), pick: fc.nat(), to: fc.nat() })
    .map(({ kind, loc, pick, to }) => {
      const p = structuredClone(plan);
      if (kind === "room") {
        const copy = structuredClone(roomAt(p, loc));
        p.floors[to % p.floors.length]!.rooms.push(copy);
        return { plan: p, rule: "duplicate_id", id: copy.id };
      }
      if (kind === "floor") {
        const f = p.floors[pick % p.floors.length]!;
        p.floors.push({ id: f.id, name: f.name, rooms: [] });
        return { plan: p, rule: "duplicate_id", id: f.id };
      }
      const node = structuredClone(p.nodes[pick % p.nodes.length]!);
      p.nodes.push(node);
      return { plan: p, rule: "duplicate_id", id: node.id };
    });
}

const breakers: Record<BrokenRule, (plan: FloorPlan) => fc.Arbitrary<Broken>> = {
  polygon: breakPolygon,
  door: breakDoor,
  node_room: breakNodeRoom,
  link: breakLink,
  duplicate_id: breakDuplicateId,
};

export const brokenRules: BrokenRule[] = ["polygon", "door", "node_room", "link", "duplicate_id"];

/** A valid plan with exactly `rule` broken once. */
export function arbBrokenFloorplan(rule: BrokenRule): fc.Arbitrary<Broken> {
  return arbFloorplan.chain(breakers[rule]);
}
