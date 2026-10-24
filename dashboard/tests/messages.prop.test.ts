import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { labelFor, parseMessage } from "../src/ws/messages";
import type { HubMessage } from "../src/ws/messages";
import { discard } from "../src/store/store";
import type { StoreState } from "../src/store/store";
import { STATE_LABELS, arbHubMessage, arbRoomStatesWith, arbStoreState } from "./arb";

const RUNS = { numRuns: 200 };

type Path = (string | number)[];
type Json = Record<string, unknown> | unknown[];

// HealthNode keys that may be absent; every other key in every message is required.
const OPTIONAL_KEYS = new Set(["measured_pps", "inferred_from", "cause", "action"]);
// floor_crew_counts is a free-form record: its keys are data, not schema.
const DICT_KEYS = new Set(["floor_crew_counts"]);
const ENUM_KEYS = new Set([
  "type", "system_state", "state", "confidence_band", "last_known_state", "alarm_time_state",
  "annotation", "link_health", "source", "role", "status", "location_kind", "marker",
]);

interface Paths {
  all: Path[]; // every non-root value
  required: Path[]; // object keys whose removal must be rejected
  enums: Path[]; // enum-valued fields
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function collect(v: unknown, path: Path = [], out: Paths = { all: [], required: [], enums: [] }): Paths {
  if (Array.isArray(v)) {
    v.forEach((x, i) => {
      out.all.push([...path, i]);
      collect(x, [...path, i], out);
    });
  } else if (isPlainObject(v)) {
    const inDict = DICT_KEYS.has(String(path[path.length - 1]));
    for (const [k, x] of Object.entries(v)) {
      const p = [...path, k];
      out.all.push(p);
      if (!inDict && !OPTIONAL_KEYS.has(k)) out.required.push(p);
      if (!inDict && ENUM_KEYS.has(k)) out.enums.push(p);
      collect(x, p, out);
    }
  }
  return out;
}

/** Deep-clones `m` and applies `f` to the parent container of `path`. */
function mutate(m: HubMessage, path: Path, f: (parent: Json, key: string | number) => void): unknown {
  const root = JSON.parse(JSON.stringify(m)) as Json;
  let parent: Json = root;
  for (const k of path.slice(0, -1)) parent = (parent as Record<string | number, unknown>)[k] as Json;
  f(parent, path[path.length - 1] as string | number);
  return root;
}

function pick<T>(xs: T[], n: number): T {
  return xs[n % xs.length] as T;
}

/** A value no field accepts in place of `v`: objects for leaves/arrays, an array for objects. */
function wrongType(v: unknown): unknown {
  return isPlainObject(v) ? [] : {};
}

/** Rejected input: parse yields null without throwing, and the Store only counts a discard. */
function expectRejected(raw: string, s: StoreState): void {
  let parsed: HubMessage | null | undefined;
  expect(() => {
    parsed = parseMessage(raw);
  }).not.toThrow();
  expect(parsed).toBeNull();
  expect(discard(s)).toEqual({ ...s, discarded: s.discarded + 1 });
}

describe("parseMessage properties", () => {
  // Feature: pwa-dashboard, Property 1: Message parsing round-trips and rejects malformed input
  it("round-trips every valid hub message", () => {
    fc.assert(
      fc.property(arbHubMessage, (m) => {
        expect(parseMessage(JSON.stringify(m))).toEqual(m);
      }),
      RUNS,
    );
  });

  // Feature: pwa-dashboard, Property 1: Message parsing round-trips and rejects malformed input
  it("rejects a message with any required field removed", () => {
    fc.assert(
      fc.property(arbHubMessage, fc.nat(), arbStoreState, (m, n, s) => {
        const path = pick(collect(m).required, n);
        const bad = mutate(m, path, (p, k) => {
          delete (p as Record<string | number, unknown>)[k];
        });
        expectRejected(JSON.stringify(bad), s);
      }),
      RUNS,
    );
  });

  // Feature: pwa-dashboard, Property 1: Message parsing round-trips and rejects malformed input
  it("rejects a message with any field set to the wrong type", () => {
    fc.assert(
      fc.property(arbHubMessage, fc.nat(), arbStoreState, (m, n, s) => {
        const path = pick(collect(m).all, n);
        const bad = mutate(m, path, (p, k) => {
          const c = p as Record<string | number, unknown>;
          c[k] = wrongType(c[k]);
        });
        expectRejected(JSON.stringify(bad), s);
      }),
      RUNS,
    );
  });

  // Feature: pwa-dashboard, Property 1: Message parsing round-trips and rejects malformed input
  it("rejects an out-of-set enum value", () => {
    fc.assert(
      fc.property(arbHubMessage, fc.nat(), fc.constantFrom("BOGUS", "", "motion", "NO DETECTION_"), arbStoreState, (m, n, v, s) => {
        const path = pick(collect(m).enums, n);
        const bad = mutate(m, path, (p, k) => {
          (p as Record<string | number, unknown>)[k] = v;
        });
        expectRejected(JSON.stringify(bad), s);
      }),
      RUNS,
    );
  });

  // Feature: pwa-dashboard, Property 1: Message parsing round-trips and rejects malformed input
  it("rejects confidence_pct outside 0..100", () => {
    const outOfRange = fc.oneof(
      fc.double({ min: -1e9, max: -1e-9, noNaN: true }),
      fc.double({ min: 100 + 1e-9, max: 1e9, noNaN: true }),
    );
    fc.assert(
      fc.property(arbRoomStatesWith({ minRooms: 1 }), fc.nat(), outOfRange, arbStoreState, (m, n, pct, s) => {
        const bad = mutate(m, ["rooms", n % m.rooms.length, "confidence_pct"], (p, k) => {
          (p as Record<string | number, unknown>)[k] = pct;
        });
        expectRejected(JSON.stringify(bad), s);
      }),
      RUNS,
    );
  });

  // Feature: pwa-dashboard, Property 1: Message parsing round-trips and rejects malformed input
  it("rejects a label that does not match its state", () => {
    fc.assert(
      fc.property(arbRoomStatesWith({ minRooms: 1 }), fc.nat(), fc.nat(), arbStoreState, (m, n, l, s) => {
        const i = n % m.rooms.length;
        const room = m.rooms[i]!;
        const wrong = pick([...STATE_LABELS, "NO_DETECTION"].filter((x) => x !== labelFor(room.state)), l);
        const bad = mutate(m, ["rooms", i, "label"], (p, k) => {
          (p as Record<string | number, unknown>)[k] = wrong;
        });
        expectRejected(JSON.stringify(bad), s);
      }),
      RUNS,
    );
  });

  // Feature: pwa-dashboard, Property 1: Message parsing round-trips and rejects malformed input
  it("never throws on arbitrary strings; anything accepted is a stable valid message", () => {
    const arbRaw = fc.oneof(fc.string(), fc.json(), fc.jsonValue().map((v) => JSON.stringify(v)));
    fc.assert(
      fc.property(arbRaw, (raw) => {
        let parsed: HubMessage | null | undefined;
        expect(() => {
          parsed = parseMessage(raw);
        }).not.toThrow();
        if (parsed != null) expect(parseMessage(JSON.stringify(parsed))).toEqual(parsed);
      }),
      RUNS,
    );
  });
});
