// State_Palette, Crew_Palette, text colors, and WCAG color math (Req 9.2–9.4, 9.7, 19.3).
// Pure, DOM-free.

import type { Band, RoomStateValue } from "../ws/messages";

/** State_Palette fills. NO_DETECTION is the darkest; every pair has contrast ≥ 1.4. */
export const STATE_PALETTE: Readonly<Record<RoomStateValue, string>> = {
  MOTION: "#FF4D2E",
  POSSIBLE: "#FFB020",
  UNKNOWN: "#6E6596",
  NO_DETECTION: "#3A4250",
};

/** Crew_Palette: crew markers never use a state color (Req 15.1). */
export const CREW_PALETTE = ["#FFFFFF", "#111111"] as const;

/** Background and text colors; each text/background pair is ≥ 4.5:1 (Req 19.3). */
export const COLORS = {
  background: "#0E1116",
  labelPlate: "#0E1116E6",
  text: "#FFFFFF",
  textOnPossible: "#111111",
  alarmRed: "#B3261E",
  wall: "#E8E6E1",
  furniture: "#2A2F38",
} as const;

/** Fill saturation per confidence band (Req 9.7). */
export const SATURATION_BY_BAND: Readonly<Record<Band, 1 | 0.75 | 0.5>> = {
  high: 1,
  medium: 0.75,
  low: 0.5,
};

type RGB = [number, number, number];

/** Parses #RGB, #RRGGBB, or #RRGGBBAA (alpha ignored) into 0..255 channels. */
export function parseHex(hex: string): RGB {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.exec(hex);
  if (!m || m[1] === undefined) throw new Error(`Bad color: ${hex}`);
  let h = m[1];
  if (h.length === 3) h = h.replace(/./g, (c) => c + c);
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

function toHex([r, g, b]: RGB): string {
  const c = (v: number) => Math.round(Math.min(255, Math.max(0, v))).toString(16).padStart(2, "0");
  return `#${c(r)}${c(g)}${c(b)}`.toUpperCase();
}

function linear(channel: number): number {
  const c = channel / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

/** WCAG 2.x relative luminance, 0 (black) .. 1 (white). */
export function relativeLuminance(hex: string): number {
  const [r, g, b] = parseHex(hex);
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

/** WCAG contrast ratio (L1 + 0.05) / (L2 + 0.05), always ≥ 1. */
export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

function toHsl([r, g, b]: RGB): [number, number, number] {
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  const d = max - min;
  if (d === 0) return [0, 0, l];
  const s = d / (1 - Math.abs(2 * l - 1));
  let h: number;
  if (max === rn) h = ((gn - bn) / d) % 6;
  else if (max === gn) h = (bn - rn) / d + 2;
  else h = (rn - gn) / d + 4;
  h *= 60;
  if (h < 0) h += 360;
  return [h, s, l];
}

function fromHsl(h: number, s: number, l: number): RGB {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  let rgb: [number, number, number];
  if (h < 60) rgb = [c, x, 0];
  else if (h < 120) rgb = [x, c, 0];
  else if (h < 180) rgb = [0, c, x];
  else if (h < 240) rgb = [0, x, c];
  else if (h < 300) rgb = [x, 0, c];
  else rgb = [c, 0, x];
  return [(rgb[0] + m) * 255, (rgb[1] + m) * 255, (rgb[2] + m) * 255];
}

/** HSL hue in degrees [0, 360). Achromatic colors return 0. */
export function hue(hex: string): number {
  return toHsl(parseHex(hex))[0];
}

/**
 * Scales HSL saturation by `factor` (1, 0.75, or 0.5 for high/medium/low).
 * Hue and lightness are kept, so the hue rule (Req 9.4) still holds.
 */
export function withSaturation(hex: string, factor: number): string {
  const [h, s, l] = toHsl(parseHex(hex));
  const f = Math.min(1, Math.max(0, factor));
  return toHex(fromHsl(h, s * f, l));
}

/** Fill for a treatment at a confidence band. */
export function fillFor(state: RoomStateValue, band: Band): string {
  return withSaturation(STATE_PALETTE[state], SATURATION_BY_BAND[band]);
}
