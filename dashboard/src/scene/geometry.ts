// Polygon geometry for the Scene_Model and renderers (Req 16.5). Pure, DOM-free.
// Area and edge length reuse the validator's implementations so both agree.

import { edgeLength, polygonArea } from "../floorplan/validate";

export { edgeLength, polygonArea };

type Point = [number, number];

/** Signed shoelace area (positive for counter-clockwise vertex order). */
function signedArea(poly: readonly Point[]): number {
  let twice = 0;
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i]!;
    const b = poly[(i + 1) % poly.length]!;
    twice += a[0] * b[1] - b[0] * a[1];
  }
  return twice / 2;
}

/**
 * Area centroid of a simple polygon (closing edge implicit).
 * Falls back to the vertex mean when the area is ~0 (degenerate input),
 * and returns [0, 0] for an empty polygon. Never returns NaN for finite input.
 */
export function centroid(poly: readonly Point[]): Point {
  if (poly.length === 0) return [0, 0];
  const a = signedArea(poly);
  if (Math.abs(a) < 1e-12) {
    let sx = 0;
    let sy = 0;
    for (const [x, y] of poly) {
      sx += x;
      sy += y;
    }
    return [sx / poly.length, sy / poly.length];
  }
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < poly.length; i++) {
    const p = poly[i]!;
    const q = poly[(i + 1) % poly.length]!;
    const cross = p[0] * q[1] - q[0] * p[1];
    cx += (p[0] + q[0]) * cross;
    cy += (p[1] + q[1]) * cross;
  }
  return [cx / (6 * a), cy / (6 * a)];
}
