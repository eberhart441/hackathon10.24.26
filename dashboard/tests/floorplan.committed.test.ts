// Unit tests for the committed hub/config/floorplan.json.
// Validates: Requirements 6.5, 6.6, 6.7
import { describe, expect, it } from "vitest";
import committedRaw from "../../hub/config/floorplan.json?raw";
import { validateFloorplan } from "../src/floorplan/validate";

const EPS = 1e-6;
const near = (a: number, b: number): boolean => Math.abs(a - b) < EPS;

type Pt = [number, number];
interface RawRoom {
  id: string;
  polygon: Pt[];
  doors: { wall: number; offset: number; width: number }[];
  simulated: boolean;
}
interface RawPlan {
  floors: { id: string; rooms: RawRoom[] }[];
}

const plan = (): RawPlan => JSON.parse(committedRaw) as RawPlan;

/** Wall i runs from polygon[i] to polygon[(i + 1) % n]. */
const wallLength = (poly: Pt[], i: number): number => {
  const a = poly[i]!;
  const b = poly[(i + 1) % poly.length]!;
  return Math.hypot(b[0] - a[0], b[1] - a[1]);
};

describe("committed floor plan", () => {
  it("passes validateFloorplan", () => {
    const v = validateFloorplan(JSON.parse(committedRaw));
    expect(v.ok).toBe(true);
  });

  it("has R1 on F1 at 3.96 m × 2.84 m with a 0.91 m corner door on a 2.84 m wall (Req 6.5)", () => {
    const p = plan();
    const f1 = p.floors.find((f) => f.id === "F1");
    expect(f1).toBeDefined();
    const ids = f1!.rooms.map((r) => r.id);
    expect(ids).toContain("R1");
    expect(ids).toContain("R2");

    const r1 = f1!.rooms.find((r) => r.id === "R1")!;
    const xs = r1.polygon.map((pt) => pt[0]);
    const ys = r1.polygon.map((pt) => pt[1]);
    const w = Math.max(...xs) - Math.min(...xs);
    const h = Math.max(...ys) - Math.min(...ys);
    expect([w, h].sort((a, b) => a - b)).toEqual([expect.closeTo(2.84, 6), expect.closeTo(3.96, 6)]);

    const cornerDoor = r1.doors.find((d) => {
      const len = wallLength(r1.polygon, d.wall);
      return (
        near(d.width, 0.91) &&
        near(len, 2.84) &&
        (near(d.offset, 0) || near(d.offset + d.width, len))
      );
    });
    expect(cornerDoor).toBeDefined();
  });

  it("marks every F2 room simulated, with 2–4 rooms if F2 exists (Req 6.6)", () => {
    const f2 = plan().floors.find((f) => f.id === "F2");
    if (!f2) return;
    expect(f2.rooms.length).toBeGreaterThanOrEqual(2);
    expect(f2.rooms.length).toBeLessThanOrEqual(4);
    expect(f2.rooms.every((r) => r.simulated === true)).toBe(true);
  });

  it("contains no MAC-like strings (Req 6.7)", () => {
    expect(committedRaw).not.toMatch(/([0-9a-f]{2}:){5}[0-9a-f]{2}/i);
  });
});
