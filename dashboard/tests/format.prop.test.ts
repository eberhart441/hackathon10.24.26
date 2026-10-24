// Feature: pwa-dashboard, Property 15: Age text round-trips
// **Validates: Requirements 12.1, 12.5**
import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { formatAge, parseAge } from "../src/scene/format";

const RUNS = { numRuns: 200 };
const MAX = 10_000_000;

const SHORT = /^\d+:[0-5]\d$/;
const LONG = /^[1-9]\d*:[0-5]\d:[0-5]\d$/;

const arbSeconds = fc.integer({ min: 0, max: MAX });
// Bias toward the hour boundary and small values, where format switches happen.
const arbBoundary = fc.oneof(
  arbSeconds,
  fc.integer({ min: 3540, max: 3660 }),
  fc.integer({ min: 0, max: 120 }),
);
const arbReal = fc.double({ min: 0, max: MAX, noNaN: true, noDefaultInfinity: true });

describe("Property 15: Age text round-trips", () => {
  it("parseAge(formatAge(s)) === s for non-negative integer seconds", () => {
    fc.assert(
      fc.property(arbBoundary, (s) => {
        expect(parseAge(formatAge(s))).toBe(s);
      }),
      RUNS,
    );
  });

  it("parseAge(formatAge(s)) === floor(s) for finite real s ≥ 0", () => {
    fc.assert(
      fc.property(arbReal, (s) => {
        expect(parseAge(formatAge(s))).toBe(Math.floor(s));
      }),
      RUNS,
    );
  });

  it("negative, NaN and ±Infinity format to 0:00", () => {
    const arbBad = fc.oneof(
      fc.double({ max: -Number.MIN_VALUE, noNaN: true }),
      fc.integer({ min: -MAX, max: -1 }),
      fc.constantFrom(NaN, Infinity, -Infinity),
    );
    fc.assert(
      fc.property(arbBad, (s) => {
        expect(formatAge(s)).toBe("0:00");
      }),
      RUNS,
    );
  });

  it("output is m:ss below one hour and h:mm:ss at or above", () => {
    fc.assert(
      fc.property(arbBoundary, (s) => {
        const text = formatAge(s);
        if (s < 3600) expect(text).toMatch(SHORT);
        else expect(text).toMatch(LONG);
      }),
      RUNS,
    );
  });

  it("formatAge is monotonic non-decreasing in parsed value", () => {
    fc.assert(
      fc.property(arbReal, arbReal, (a, b) => {
        const [lo, hi] = a <= b ? [a, b] : [b, a];
        expect(parseAge(formatAge(lo))).toBeLessThanOrEqual(parseAge(formatAge(hi)));
      }),
      RUNS,
    );
  });
});
