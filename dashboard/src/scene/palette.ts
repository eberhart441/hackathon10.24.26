import type { Band, RoomStateCode } from '../types';

// State_Palette (Kiro glossary). Hues avoid 75–165° so no state reads as "green / safe".
export const STATE_FILL: Record<RoomStateCode, string> = {
  MOTION: '#FF4D2E',
  POSSIBLE: '#FFB020',
  UNKNOWN: '#6E6596',
  NO_DETECTION: '#3A4250',
};

export const STATE_LABEL: Record<RoomStateCode, string> = {
  MOTION: 'MOTION',
  POSSIBLE: 'POSSIBLE',
  UNKNOWN: 'UNKNOWN',
  NO_DETECTION: 'NO DETECTION',
};

export type PatternId = 'solid' | 'hatch' | 'crosshatch' | 'dots';

export const STATE_PATTERN: Record<RoomStateCode, PatternId> = {
  MOTION: 'solid',
  POSSIBLE: 'hatch',
  UNKNOWN: 'crosshatch',
  NO_DETECTION: 'dots',
};

export const CREW_PALETTE = ['#FFFFFF', '#111111'] as const;
export const GREY_FILL = '#4B5059';
export const ALARM_RED = '#B3121B';
export const THEME_DEFAULT = '#0B0F14';

export const BAND_SATURATION: Record<Band, number> = { high: 1, medium: 0.75, low: 0.5 };

export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
}

export function rgbToHex([r, g, b]: [number, number, number]): string {
  return '#' + [r, g, b].map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('');
}

// WCAG relative luminance.
export function luminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex).map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

export function hue(hex: string): number {
  const [r, g, b] = hexToRgb(hex).map((v) => v / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const d = max - min;
  if (d === 0) return 0;
  let h: number;
  if (max === r) h = ((g - b) / d) % 6;
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  return (h * 60 + 360) % 360;
}

// Lower confidence = less saturated fill; the pattern stays the same (Kiro R9.7).
export function desaturate(hex: string, saturation: number): string {
  const rgb = hexToRgb(hex);
  const grey = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2];
  return rgbToHex(rgb.map((c) => grey + (c - grey) * saturation) as [number, number, number]);
}
