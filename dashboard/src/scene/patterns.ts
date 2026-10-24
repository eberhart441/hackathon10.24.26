// Treatment → pattern/icon encoding and procedural pattern data (Req 9.2, 9.9).
// One shape list per pattern feeds both the SVG <pattern> markup (2D) and the
// canvas painter (3D CanvasTexture), so both renderers draw the same tile.
// Pure, DOM-free.

import type { RoomStateValue, StateLabel } from "../ws/messages";
import { labelFor } from "../ws/messages";
import { STRINGS } from "./strings";

export type PatternId = "solid" | "hatch45" | "crosshatch" | "dots";
export type IconId = "wave" | "outline-question" | "question" | "dash";

export interface TreatmentEncoding {
  pattern: PatternId;
  icon: IconId;
  label: StateLabel;
}

/** Pattern, icon, and label depend only on the treatment (Req 9.2). */
export const TREATMENTS: Readonly<Record<RoomStateValue, TreatmentEncoding>> = {
  MOTION: { pattern: "solid", icon: "wave", label: labelFor("MOTION") },
  POSSIBLE: { pattern: "hatch45", icon: "outline-question", label: labelFor("POSSIBLE") },
  UNKNOWN: { pattern: "crosshatch", icon: "question", label: labelFor("UNKNOWN") },
  NO_DETECTION: { pattern: "dots", icon: "dash", label: labelFor("NO_DETECTION") },
};

/** Tile size in world meters: hatch spacing is the same in every room. */
export const PATTERN_SPACING_M = 0.25;

// Shapes are in unit-tile coordinates (0..1); renderers scale by tile size.
export type PatternShape =
  | { kind: "line"; x1: number; y1: number; x2: number; y2: number; width: number }
  | { kind: "dot"; cx: number; cy: number; r: number };

export interface PatternDef {
  id: PatternId;
  ink: string; // stroke/dot color drawn over the room fill
  inkOpacity: number;
  shapes: readonly PatternShape[];
}

// 45° diagonal from bottom-left to top-right, plus the two corner pieces so tiles join seamlessly.
function diagonal(width: number): PatternShape[] {
  return [
    { kind: "line", x1: 0, y1: 1, x2: 1, y2: 0, width },
    { kind: "line", x1: -0.5, y1: 0.5, x2: 0.5, y2: -0.5, width },
    { kind: "line", x1: 0.5, y1: 1.5, x2: 1.5, y2: 0.5, width },
  ];
}

function antiDiagonal(width: number): PatternShape[] {
  return [
    { kind: "line", x1: 0, y1: 0, x2: 1, y2: 1, width },
    { kind: "line", x1: -0.5, y1: 0.5, x2: 0.5, y2: 1.5, width },
    { kind: "line", x1: 0.5, y1: -0.5, x2: 1.5, y2: 0.5, width },
  ];
}

// Deterministic "fine static noise" for UNKNOWN (seeded LCG, no Math.random).
function noise(count: number, seed: number): PatternShape[] {
  let x = seed >>> 0;
  const next = () => {
    x = (Math.imul(x, 1664525) + 1013904223) >>> 0;
    return x / 2 ** 32;
  };
  const out: PatternShape[] = [];
  for (let i = 0; i < count; i++) out.push({ kind: "dot", cx: next(), cy: next(), r: 0.025 });
  return out;
}

export const PATTERNS: Readonly<Record<PatternId, PatternDef>> = {
  solid: { id: "solid", ink: "#0E1116", inkOpacity: 0, shapes: [] },
  hatch45: { id: "hatch45", ink: "#0E1116", inkOpacity: 0.55, shapes: diagonal(0.14) },
  crosshatch: {
    id: "crosshatch",
    ink: "#E6E2F2",
    inkOpacity: 0.45,
    shapes: [...diagonal(0.08), ...antiDiagonal(0.08), ...noise(6, 0x5eed)],
  },
  dots: { id: "dots", ink: "#9AA3B2", inkOpacity: 0.6, shapes: [{ kind: "dot", cx: 0.5, cy: 0.5, r: 0.09 }] },
};

/** "SIMULATED" overlay on simulated rooms' floors (Req 9.9). */
export const SIMULATED_OVERLAY = {
  text: STRINGS.simulated,
  angleDeg: 30,
  opacity: 0.25,
  color: "#FFFFFF",
  fontSizeM: 0.22,
  spacingXM: 1.6, // horizontal repeat in meters
  spacingYM: 0.6, // vertical repeat in meters
} as const;

/** SVG element id for a pattern, so <defs> and fills agree. */
export function svgPatternId(id: PatternId): string {
  return `rs-pattern-${id}`;
}

function n(v: number): string {
  return String(Math.round(v * 1e6) / 1e6);
}

/**
 * SVG `<pattern>` markup for one pattern, tiled in user-space meters
 * (`tileM` defaults to PATTERN_SPACING_M). Draws ink only; the room fill is
 * a separate layer under it. Returns "" for "solid".
 */
export function svgPatternMarkup(id: PatternId, tileM: number = PATTERN_SPACING_M): string {
  const def = PATTERNS[id];
  if (def.shapes.length === 0) return "";
  const body = def.shapes
    .map((s) =>
      s.kind === "line"
        ? `<line x1="${n(s.x1 * tileM)}" y1="${n(s.y1 * tileM)}" x2="${n(s.x2 * tileM)}" y2="${n(s.y2 * tileM)}" stroke-width="${n(s.width * tileM)}"/>`
        : `<circle cx="${n(s.cx * tileM)}" cy="${n(s.cy * tileM)}" r="${n(s.r * tileM)}"/>`,
    )
    .join("");
  return (
    `<pattern id="${svgPatternId(id)}" patternUnits="userSpaceOnUse" width="${n(tileM)}" height="${n(tileM)}">` +
    `<g stroke="${def.ink}" fill="${def.ink}" opacity="${n(def.inkOpacity)}" stroke-linecap="square">${body}</g>` +
    `</pattern>`
  );
}

/** The subset of CanvasRenderingContext2D the painter uses. */
export interface PatternCanvas {
  fillStyle: unknown;
  strokeStyle: unknown;
  lineWidth: number;
  globalAlpha: number;
  lineCap: string;
  save(): void;
  restore(): void;
  beginPath(): void;
  rect(x: number, y: number, w: number, h: number): void;
  clip(): void;
  moveTo(x: number, y: number): void;
  lineTo(x: number, y: number): void;
  arc(x: number, y: number, r: number, start: number, end: number): void;
  stroke(): void;
  fill(): void;
  fillRect(x: number, y: number, w: number, h: number): void;
}

/**
 * Paints one square tile of `sizePx` pixels for pattern `id` at (0, 0).
 * If `fill` is given, the tile is filled with it first; otherwise only the ink
 * is drawn. The tile repeats seamlessly (e.g. as a RepeatWrapping CanvasTexture).
 */
export function paintPattern(ctx: PatternCanvas, id: PatternId, sizePx: number, fill?: string): void {
  const def = PATTERNS[id];
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, 0, sizePx, sizePx);
  ctx.clip();
  if (fill !== undefined) {
    ctx.globalAlpha = 1;
    ctx.fillStyle = fill;
    ctx.fillRect(0, 0, sizePx, sizePx);
  }
  ctx.globalAlpha = def.inkOpacity;
  ctx.strokeStyle = def.ink;
  ctx.fillStyle = def.ink;
  ctx.lineCap = "square";
  for (const s of def.shapes) {
    ctx.beginPath();
    if (s.kind === "line") {
      ctx.lineWidth = s.width * sizePx;
      ctx.moveTo(s.x1 * sizePx, s.y1 * sizePx);
      ctx.lineTo(s.x2 * sizePx, s.y2 * sizePx);
      ctx.stroke();
    } else {
      ctx.arc(s.cx * sizePx, s.cy * sizePx, s.r * sizePx, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();
}
