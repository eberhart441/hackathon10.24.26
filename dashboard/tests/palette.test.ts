import { describe, expect, it } from "vitest";
import type { RoomStateValue } from "../src/ws/messages";
import {
  COLORS,
  CREW_PALETTE,
  STATE_PALETTE,
  contrastRatio,
  hue,
  relativeLuminance,
  withSaturation,
} from "../src/scene/palette";
import { PATTERNS, TREATMENTS, paintPattern, svgPatternMarkup, type PatternCanvas } from "../src/scene/patterns";

const STATES: RoomStateValue[] = ["MOTION", "POSSIBLE", "UNKNOWN", "NO_DETECTION"];

describe("color math", () => {
  it("matches WCAG endpoints", () => {
    expect(relativeLuminance("#000000")).toBe(0);
    expect(relativeLuminance("#FFFFFF")).toBeCloseTo(1, 10);
    expect(contrastRatio("#FFFFFF", "#000000")).toBeCloseTo(21, 10);
    expect(contrastRatio("#000000", "#FFFFFF")).toBeCloseTo(21, 10);
  });

  it("computes hues", () => {
    expect(hue("#FF0000")).toBeCloseTo(0);
    expect(hue("#00FF00")).toBeCloseTo(120);
    expect(hue("#0000FF")).toBeCloseTo(240);
  });

  it("withSaturation keeps the color at 1 and greys it at 0", () => {
    expect(withSaturation("#FF4D2E", 1)).toBe("#FF4D2E");
    const grey = withSaturation("#FF4D2E", 0);
    expect(grey.slice(1, 3)).toBe(grey.slice(3, 5));
    expect(grey.slice(3, 5)).toBe(grey.slice(5, 7));
  });
});

describe("State_Palette", () => {
  it("gives every pair of states a contrast ratio of at least 1.4", () => {
    for (const a of STATES) {
      for (const b of STATES) {
        if (a !== b) expect(contrastRatio(STATE_PALETTE[a], STATE_PALETTE[b]), `${a}/${b}`).toBeGreaterThanOrEqual(1.4);
      }
    }
  });

  it("makes NO_DETECTION the darkest", () => {
    const nd = relativeLuminance(STATE_PALETTE.NO_DETECTION);
    for (const s of STATES) if (s !== "NO_DETECTION") expect(relativeLuminance(STATE_PALETTE[s])).toBeGreaterThan(nd);
  });

  it("uses no hue in 75–165° at any saturation step", () => {
    for (const s of STATES) {
      for (const f of [1, 0.75, 0.5]) {
        const h = hue(withSaturation(STATE_PALETTE[s], f));
        expect(h >= 75 && h <= 165, `${s}@${f}: ${h}`).toBe(false);
      }
    }
  });
});

describe("text and crew colors", () => {
  it("meets 4.5:1 for text", () => {
    expect(contrastRatio(COLORS.text, COLORS.background)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(COLORS.text, COLORS.labelPlate)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(COLORS.textOnPossible, STATE_PALETTE.POSSIBLE)).toBeGreaterThanOrEqual(4.5);
  });

  it("crew palette is white and near-black only", () => {
    expect([...CREW_PALETTE]).toEqual(["#FFFFFF", "#111111"]);
  });
});

describe("patterns", () => {
  it("maps each treatment to its own pattern and icon", () => {
    expect(TREATMENTS.MOTION).toEqual({ pattern: "solid", icon: "wave", label: "MOTION" });
    expect(TREATMENTS.POSSIBLE).toEqual({ pattern: "hatch45", icon: "outline-question", label: "POSSIBLE" });
    expect(TREATMENTS.UNKNOWN).toEqual({ pattern: "crosshatch", icon: "question", label: "UNKNOWN" });
    expect(TREATMENTS.NO_DETECTION).toEqual({ pattern: "dots", icon: "dash", label: "NO DETECTION" });
  });

  it("emits SVG pattern markup tiled at 0.25 m", () => {
    const svg = svgPatternMarkup("hatch45");
    expect(svg).toContain('patternUnits="userSpaceOnUse"');
    expect(svg).toContain('width="0.25"');
    expect(svgPatternMarkup("solid")).toBe("");
  });

  it("paints one stroke per line and one fill per dot, plus the background", () => {
    const calls: string[] = [];
    const ctx: PatternCanvas = {
      fillStyle: "",
      strokeStyle: "",
      lineWidth: 1,
      globalAlpha: 1,
      lineCap: "butt",
      save: () => calls.push("save"),
      restore: () => calls.push("restore"),
      beginPath: () => {},
      rect: () => {},
      clip: () => {},
      moveTo: () => {},
      lineTo: () => {},
      arc: () => {},
      stroke: () => calls.push("stroke"),
      fill: () => calls.push("fill"),
      fillRect: () => calls.push("fillRect"),
    };
    paintPattern(ctx, "crosshatch", 64, STATE_PALETTE.UNKNOWN);
    const lines = PATTERNS.crosshatch.shapes.filter((s) => s.kind === "line").length;
    const dots = PATTERNS.crosshatch.shapes.length - lines;
    expect(calls.filter((c) => c === "stroke")).toHaveLength(lines);
    expect(calls.filter((c) => c === "fill")).toHaveLength(dots);
    expect(calls.filter((c) => c === "fillRect")).toHaveLength(1);
    expect(calls[0]).toBe("save");
    expect(calls.at(-1)).toBe("restore");
  });
});
