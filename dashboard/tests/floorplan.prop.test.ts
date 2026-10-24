// Feature: pwa-dashboard, Property 16: The floor-plan validator accepts valid plans and names every broken rule
// **Validates: Requirements 6.3, 6.4**
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { validateFloorplan } from "../src/floorplan/validate";
import { arbBrokenFloorplan, arbFloorplan, brokenRules } from "./arbFloorplan";

const RUNS = { numRuns: 200 };

describe("Property 16: floor-plan validator", () => {
  it("accepts every valid plan and round-trips it through JSON unchanged", () => {
    fc.assert(
      fc.property(arbFloorplan, (plan) => {
        const direct = validateFloorplan(plan);
        expect(direct.ok).toBe(true);
        const v = validateFloorplan(JSON.parse(JSON.stringify(plan)));
        expect(v.ok).toBe(true);
        if (v.ok) expect(v.plan).toEqual(plan);
      }),
      RUNS,
    );
  });

  for (const rule of brokenRules) {
    it(`rejects a plan with one broken "${rule}" rule and names the item`, () => {
      fc.assert(
        fc.property(arbBrokenFloorplan(rule), (b) => {
          const v = validateFloorplan(JSON.parse(JSON.stringify(b.plan)));
          expect(v.ok).toBe(false);
          if (v.ok) return;
          expect(v.errors.some((e) => e.rule === b.rule && e.id === b.id)).toBe(true);
          // Only the broken rule fires: no cascading errors from other rules.
          expect(v.errors.every((e) => e.rule === b.rule)).toBe(true);
          expect(v.errors.every((e) => typeof e.message === "string" && e.message.length > 0)).toBe(true);
        }),
        RUNS,
      );
    });
  }

  it("never throws on arbitrary input", () => {
    fc.assert(
      fc.property(fc.anything(), (input) => {
        const v = validateFloorplan(input);
        expect(typeof v.ok).toBe("boolean");
        if (!v.ok) expect(v.errors.length).toBeGreaterThan(0);
      }),
      { numRuns: 500 },
    );
  });
});
