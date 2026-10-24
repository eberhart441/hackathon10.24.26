// Draws the team's own app icon (floor-plan outline + signal arcs) as PNGs. No third-party art.
// Run: node scripts/make-icons.mjs
import { mkdirSync, writeFileSync } from 'node:fs';
import { deflateSync } from 'node:zlib';

const OUT = new URL('../public/icons/', import.meta.url);
mkdirSync(OUT, { recursive: true });

const BG = [11, 15, 20];
const WALL = [228, 222, 212];
const AMBER = [255, 176, 32];
const RED = [255, 77, 46];

function crc32(buf) {
  let c;
  const table = [];
  for (let n = 0; n < 256; n++) {
    c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  let crc = 0xffffffff;
  for (const b of buf) crc = table[(crc ^ b) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function png(size, pixels) {
  const chunk = (type, data) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type), data]);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(td));
    return Buffer.concat([len, td, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8;
  ihdr[9] = 6; // RGBA
  const raw = Buffer.alloc((size * 4 + 1) * size);
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0;
    pixels.copy(raw, y * (size * 4 + 1) + 1, y * size * 4, (y + 1) * size * 4);
  }
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

// Shape in unit square [0,1]^2. Returns [r,g,b,a] or null.
function shade(u, v, inset) {
  // Map into safe zone for maskable icons.
  const s = 1 - 2 * inset;
  const x = (u - inset) / s;
  const y = (v - inset) / s;
  const segDist = (px, py, ax, ay, bx, by) => {
    const t = Math.max(0, Math.min(1, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)));
    return Math.hypot(px - (ax + t * (bx - ax)), py - (ay + t * (by - ay)));
  };
  // Two-room plan outline with a door gap.
  const walls = [
    [0.16, 0.3, 0.84, 0.3],
    [0.84, 0.3, 0.84, 0.84],
    [0.84, 0.84, 0.16, 0.84],
    [0.16, 0.84, 0.16, 0.62],
    [0.16, 0.48, 0.16, 0.3],
    [0.52, 0.3, 0.52, 0.5],
    [0.52, 0.64, 0.52, 0.84],
  ];
  let best = 1;
  for (const w of walls) best = Math.min(best, segDist(x, y, ...w));
  if (best < 0.035) return WALL;
  // Priority room fill (left) and signal arcs above.
  if (x > 0.2 && x < 0.48 && y > 0.34 && y < 0.8) return RED;
  const r = Math.hypot(x - 0.68, y - 0.62);
  for (const ring of [0.1, 0.18]) if (Math.abs(r - ring) < 0.025 && y < 0.62 + 0.02) return AMBER;
  if (r < 0.04) return AMBER;
  return null;
}

function draw(size, { inset = 0.06, rounded = true } = {}) {
  const px = Buffer.alloc(size * size * 4);
  const SS = 3;
  for (let y = 0; y < size; y++)
    for (let x = 0; x < size; x++) {
      let acc = [0, 0, 0, 0];
      for (let sy = 0; sy < SS; sy++)
        for (let sx = 0; sx < SS; sx++) {
          const u = (x + (sx + 0.5) / SS) / size;
          const v = (y + (sy + 0.5) / SS) / size;
          const corner = 0.18;
          const dx = Math.max(corner - u, u - (1 - corner), 0);
          const dy = Math.max(corner - v, v - (1 - corner), 0);
          const inside = !rounded || Math.hypot(dx, dy) <= corner;
          if (!inside) continue;
          const c = shade(u, v, inset) ?? BG;
          acc = [acc[0] + c[0], acc[1] + c[1], acc[2] + c[2], acc[3] + 255];
        }
      const n = SS * SS;
      const i = (y * size + x) * 4;
      const a = acc[3] / n;
      px[i] = a ? acc[0] / (acc[3] / 255) : 0;
      px[i + 1] = a ? acc[1] / (acc[3] / 255) : 0;
      px[i + 2] = a ? acc[2] / (acc[3] / 255) : 0;
      px[i + 3] = a;
    }
  return png(size, px);
}

writeFileSync(new URL('icon-192.png', OUT), draw(192));
writeFileSync(new URL('icon-512.png', OUT), draw(512));
writeFileSync(new URL('icon-maskable-512.png', OUT), draw(512, { inset: 0.16, rounded: false }));
// iOS adds its own rounded mask, so the touch icon is a full square.
writeFileSync(new URL('apple-touch-icon.png', OUT), draw(180, { inset: 0.08, rounded: false }));
writeFileSync(
  new URL('favicon.svg', OUT),
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="12" fill="#0B0F14"/><rect x="14" y="22" width="16" height="28" fill="#FF4D2E"/><path d="M11 19h42v36H11V39M11 31V19M33 19v13M33 41v14" fill="none" stroke="#E4DED4" stroke-width="4"/></svg>\n`,
);
console.log('icons written');
