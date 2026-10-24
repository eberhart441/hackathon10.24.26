import { describe, expect, it } from 'vitest';
import fc from 'fast-check';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { STATE_FILL, contrast, hue, luminance } from '../src/scene/palette';
import { ageText } from '../src/scene/format';
import { validateFloorplan } from '../src/floorplan/validate';
import { parseMessage } from '../src/ws/parse';
import { workbox } from '../vite.config';
import { PLAN } from './arbitraries';

const SRC = join(__dirname, '..', 'src');
const STATIC = join(__dirname, '..', '..', 'hub', 'static');
const MAC = /([0-9a-f]{2}:){5}[0-9a-f]{2}/i;

function files(dir: string, exts: string[]): string[] {
  return readdirSync(dir).flatMap((f: string) => {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) return files(p, exts);
    return exts.some((e) => p.endsWith(e)) ? [p] : [];
  });
}

describe('palette (Kiro R9.3, R9.4)', () => {
  const states = Object.keys(STATE_FILL) as (keyof typeof STATE_FILL)[];
  it('every pair of states differs by a contrast ratio of at least 1.4', () => {
    for (const a of states) for (const b of states) if (a !== b) expect(contrast(STATE_FILL[a], STATE_FILL[b])).toBeGreaterThanOrEqual(1.4);
  });
  it('NO DETECTION is the darkest state', () => {
    for (const s of states) if (s !== 'NO_DETECTION') expect(luminance(STATE_FILL.NO_DETECTION)).toBeLessThan(luminance(STATE_FILL[s]));
  });
  it('no state colour is green (hue 75–165°)', () => {
    for (const s of states) {
      const h = hue(STATE_FILL[s]);
      expect(h < 75 || h > 165).toBe(true);
    }
  });
});

describe('format', () => {
  it('Age_Text is m:ss below an hour and h:mm:ss above', () => {
    expect(ageText(42)).toBe('0:42');
    expect(ageText(605)).toBe('10:05');
    expect(ageText(3725)).toBe('1:02:05');
  });
});

describe('floor plan validator (Kiro R6.3, R6.4)', () => {
  it('accepts the committed floor plan', () => {
    expect(validateFloorplan(PLAN).ok).toBe(true);
  });
  it('explains a door that does not fit, a missing node room, and duplicate ids', () => {
    const bad = structuredClone(PLAN);
    bad.floors[0].rooms[0].doors[0].width = 9;
    bad.nodes[0].room = 'NOPE';
    bad.floors[1].rooms[0].id = 'R1';
    bad.links.push({ tx: 'RX1', rx: 'TX1' });
    const r = validateFloorplan(bad);
    expect(r.ok).toBe(false);
    const text = (r as { errors: string[] }).errors.join('\n');
    expect(text).toMatch(/door 1 does not fit its wall/);
    expect(text).toMatch(/points to room "NOPE"/);
    expect(text).toMatch(/Room id "R1" is used more than once/);
    expect(text).toMatch(/"RX1" is not an existing TX node/);
  });
  it('never throws on arbitrary JSON', () => {
    fc.assert(fc.property(fc.jsonValue(), (v) => void validateFloorplan(v)), { numRuns: 300 });
  });
});

describe('message parsing (Kiro R7.2)', () => {
  it('discards anything malformed without throwing', () => {
    fc.assert(fc.property(fc.oneof(fc.string(), fc.jsonValue()), (v) => {
      const m = parseMessage(typeof v === 'string' ? v : JSON.stringify(v));
      if (m) expect(['room_states', 'health', 'crew', 'recording']).toContain(m.type);
    }), { numRuns: 300 });
  });
  it('accepts the design-doc example', () => {
    const msg = {
      type: 'recording', ts: 1730000000.0, indicator: 'Recording (alarm)', stored_samples: 128, fault: null,
    };
    expect(parseMessage(JSON.stringify(msg))).toMatchObject({ type: 'recording', indicator: 'Recording (alarm)' });
  });
});

describe('privacy and wording (Kiro R6.7, R9.6, R17)', () => {
  it('the service worker has no runtime caching and never serves /api or /ws from cache', () => {
    expect(workbox.runtimeCaching).toEqual([]);
    expect(workbox.navigateFallbackDenylist.some((r) => r.test('/api/floorplan'))).toBe(true);
    expect(workbox.navigateFallbackDenylist.some((r) => r.test('/ws'))).toBe(true);
  });

  it('only the token key is ever written to localStorage', () => {
    const writes = files(SRC, ['.ts', '.tsx'])
      .map((f) => readFileSync(f, 'utf8'))
      .flatMap((s) => [...s.matchAll(/(localStorage|sessionStorage|indexedDB|caches)\.\w+\(([^)]*)\)/g)].map((m) => m[0]));
    for (const w of writes) expect(w).toMatch(/^localStorage\.(getItem|setItem|removeItem)\(TOKEN_KEY/);
  });

  it('no user-facing source text contains a banned word', () => {
    for (const f of files(SRC, ['.tsx', '.ts'])) {
      const code = readFileSync(f, 'utf8')
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/(^|[^:])\/\/.*$/gm, '$1');
      const strings = [...code.matchAll(/'([^'\n]*)'|"([^"\n]*)"|`([^`]*)`|>([^<>{}\n]+)</g)].map((m) => m[1] ?? m[2] ?? m[3] ?? m[4]);
      for (const s of strings) expect(s, `${f}: ${s}`).not.toMatch(/\b(empty|clear(ed)?|safe)\b/i);
    }
  });

  it('no MAC-address-like string in the floor plan or the built bundle', () => {
    expect(JSON.stringify(PLAN)).not.toMatch(MAC);
    if (!existsSync(STATIC)) return;
    for (const f of files(STATIC, ['.js', '.html', '.webmanifest'])) expect(readFileSync(f, 'utf8')).not.toMatch(MAC);
  });

  it('the built app references no external origin (Kiro R18.1)', () => {
    if (!existsSync(STATIC)) return;
    for (const f of files(STATIC, ['.html', '.css', '.webmanifest'])) {
      expect(readFileSync(f, 'utf8')).not.toMatch(/(src|href)=["']https?:\/\//);
      expect(readFileSync(f, 'utf8')).not.toMatch(/url\(["']?https?:\/\//);
    }
  });
});
