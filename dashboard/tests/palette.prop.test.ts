// Feature: pwa-dashboard, Property 9: The State_Palette is grayscale-distinguishable and never green
// **Validates: Requirements 9.2, 9.3, 9.4, 19.3**
import { describe, expect, it } from "vitest";
import fc from "fast-check";
import type { Band, RoomStateValue } from "../src/ws/messages";
import {
  COLORS,
  CREW_PALETTE,
  SATURATION_BY_BAND,
  STATE_PALETTE,
  contrastRatio,
  fillFor,
  hue,
  parseHex,
  relativeLuminance,
  withSaturation,
} from "../src/scene/palette";
import { TREATMENTS } from "../src/scene/patterns";

const RUNS = { numRuns: 200 };

const STATES: RoomStateValue[] = ["MOTION", "POSSIBLE", "UNKNOWN", "NO_DETECTION"];
const BANDS: Band[] = ["high", "medium", "low"];

const arbState = fc.constantFrom(...STATES);
const arbBand = fc.constantFrom(...BANDS);
const arbDistinctStates = fc
  .tuple(arbState, arbState)
  .filter(([a, b]) => a !== b);

const toHex2 = (v: number) => v.toString(16).padStart(2, "0");
const arbRgb = fc.tuple(
  fc.integer({ min: 0, max: 255 }),
  fc.integer({ min: 0, max: 255 }),
  fc.integer({ min: 0, max: 255 }),
);
const rgbHex = ([r, g, b]: [number, number, number], upper: boolean) => {
  const h = `#${toHex2(r)}${toHex2(g)}${toHex2(b)}`;
  return upper ? h.toUpperCase() : h;
};
const arbHex = fc.tuple(arbRgb, fc.boolean()).map(([rgb, upper]) => rgbHex(rgb, upper));

// Any saturation factor a renderer could use: the three band steps or anything in [0, 1].
const arbFactor = fc.oneof(
  fc.constantFrom(...Object.values(SATURATION_BY_BAND)),
  fc.double({ min: 0, max: 1, noNaN: true }),
);

const isGreen = (h: number) => h >= 75 && h <= 165;
const hueDistance = (a: number, b: number) => {
  const d = Math.abs(a - b) % 360;
  return Math.min(d, 360 - d);
};
const lightness = (hex: string) => {
  const [r, g, b] = parseHex(hex);
  return (Math.max(r, g, b) + Math.min(r, g, b)) / 2 / 255;
};
const chroma255 = (hex: string) => {
  const [r, g, b] = parseHex(hex);
  return Math.max(r, g, b) - Math.min(r, g, b);
};

describe("Property 9: The State_Palette is grayscale-distinguishable and never green", () => {
  it("fillFor never yields a hue in 75–165° for any pair of states at any bands", () => {
    fc.assert(
      fc.property(arbDistinctStates, arbBand, arbBand, ([a, b], ba, bb) => {
        for (const [s, band] of [[a, ba], [b, bb]] as const) {
          const h = hue(fillFor(s, band));
          expect(isGreen(h), `${s}@${band}: hue ${h}`).toBe(false);
        }
      }),
      RUNS,
    );
  });

  it("full-saturation fills of distinct states have contrast ≥ 1.4 and NO_DETECTION is darkest", () => {
    const nd = relativeLuminance(STATE_PALETTE.NO_DETECTION);
    fc.assert(
      fc.property(arbDistinctStates, ([a, b]) => {
        expect(contrastRatio(fillFor(a, "high"), fillFor(b, "high"))).toBeGreaterThanOrEqual(1.4);
        for (const s of [a, b]) {
          if (s !== "NO_DETECTION") expect(relativeLuminance(STATE_PALETTE[s])).toBeGreaterThan(nd);
        }
      }),
      RUNS,
    );
  });

  it("distinct states differ in pattern, icon, and label", () => {
    fc.assert(
      fc.property(arbDistinctStates, ([a, b]) => {
        const ta = TREATMENTS[a];
        const tb = TREATMENTS[b];
        expect(ta.pattern).not.toBe(tb.pattern);
        expect(ta.icon).not.toBe(tb.icon);
        expect(ta.label).not.toBe(tb.label);
      }),
      RUNS,
    );
  });

  it("text colors meet 4.5:1 on the background, label plate, and POSSIBLE badge", () => {
    const pairs: [string, string][] = [
      [COLORS.text, COLORS.background],
      [COLORS.text, COLORS.labelPlate],
      [COLORS.textOnPossible, STATE_PALETTE.POSSIBLE],
    ];
    fc.assert(
      fc.property(fc.constantFrom(...pairs), fc.boolean(), ([fg, bg], swap) => {
        const ratio = swap ? contrastRatio(bg, fg) : contrastRatio(fg, bg);
        expect(ratio).toBeGreaterThanOrEqual(4.5);
      }),
      RUNS,
    );
  });

  it("crew colors are never a state color at any saturation", () => {
    const crew = new Set<string>(CREW_PALETTE.map((c) => c.toUpperCase()));
    fc.assert(
      fc.property(arbState, arbFactor, (s, f) => {
        expect(crew.has(withSaturation(STATE_PALETTE[s], f).toUpperCase())).toBe(false);
        expect(crew.has(STATE_PALETTE[s].toUpperCase())).toBe(false);
      }),
      RUNS,
    );
  });

  it("withSaturation keeps hue (within 1°) and lightness for arbitrary colors", () => {
    fc.assert(
      fc.property(arbHex, arbFactor, (hex, f) => {
        const out = withSaturation(hex, f);
        // Lightness survives 8-bit rounding to within one channel step.
        expect(Math.abs(lightness(out) - lightness(hex))).toBeLessThanOrEqual(1 / 255 + 1e-9);
        // Hue is only well defined (to 1° after 8-bit rounding) when the output has enough chroma.
        if (chroma255(out) >= 120) {
          expect(hueDistance(hue(out), hue(hex))).toBeLessThanOrEqual(1);
        }
      }),
      RUNS,
    );
  });

  it("withSaturation keeps hue within 1° for chromatic outputs", () => {
    // Smart generator: colors with chroma high enough that the scaled output stays chromatic.
    const arbChromatic = fc
      .tuple(arbRgb, fc.double({ min: 0.5, max: 1, noNaN: true }))
      .filter(([[r, g, b], f]) => (Math.max(r, g, b) - Math.min(r, g, b)) * f >= 128);
    fc.assert(
      fc.property(arbChromatic, ([rgb, f]) => {
        const hex = rgbHex(rgb, true);
        expect(hueDistance(hue(withSaturation(hex, f)), hue(hex))).toBeLessThanOrEqual(1);
      }),
      RUNS,
    );
  });

  it("contrastRatio is symmetric and ≥ 1", () => {
    fc.assert(
      fc.property(arbHex, arbHex, (a, b) => {
        const ab = contrastRatio(a, b);
        expect(ab).toBe(contrastRatio(b, a));
        expect(ab).toBeGreaterThanOrEqual(1);
        expect(contrastRatio(a, a)).toBe(1);
      }),
      RUNS,
    );
  });
});
