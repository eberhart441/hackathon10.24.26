// Feature: pwa-dashboard, Property 19: Reconnect backoff stays within bounds
// **Validates: Requirements 7.4**
import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { BACKOFF_BASE_MS, BACKOFF_CAP_MS, backoffMs } from "../src/ws/backoff";
import { createWsClient, type WsLike } from "../src/ws/client";

const RUNS = { numRuns: 200 };
const MIN = 500;
const MAX = 5000;

// Any JS number: integers, doubles, negatives, NaN, ±Infinity, ±0.
const arbAnyNumber = fc.oneof(
  fc.integer(),
  fc.double(),
  fc.constantFrom(Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, -0, Number.MAX_VALUE),
);
// Small attempts hit the doubling region; larger ones hit the cap.
const arbAttempt = fc.oneof(fc.integer({ min: 0, max: 10 }), fc.integer({ min: 0, max: 1_000_000 }));

describe("Property 19: Reconnect backoff stays within bounds", () => {
  it("constants match the spec", () => {
    expect(BACKOFF_BASE_MS).toBe(MIN);
    expect(BACKOFF_CAP_MS).toBe(MAX);
  });

  it("backoffMs(x) is a finite integer in [500, 5000] for any number", () => {
    fc.assert(
      fc.property(arbAnyNumber, (x) => {
        const d = backoffMs(x);
        expect(Number.isInteger(d)).toBe(true);
        expect(d).toBeGreaterThanOrEqual(MIN);
        expect(d).toBeLessThanOrEqual(MAX);
      }),
      RUNS,
    );
  });

  it("backoffMs(n) === min(500·2^n, 5000) for integer n ≥ 0", () => {
    fc.assert(
      fc.property(arbAttempt, (n) => {
        expect(backoffMs(n)).toBe(Math.min(MIN * 2 ** n, MAX));
      }),
      RUNS,
    );
  });

  it("is non-decreasing in attempt", () => {
    fc.assert(
      fc.property(arbAttempt, fc.integer({ min: 0, max: 20 }), (n, k) => {
        expect(backoffMs(n)).toBeLessThanOrEqual(backoffMs(n + 1));
        expect(backoffMs(n)).toBeLessThanOrEqual(backoffMs(n + k));
      }),
      RUNS,
    );
  });

  it("n consecutive failures wait at most 5000·n total and never more than 5 s each", () => {
    fc.assert(
      fc.property(fc.integer({ min: 1, max: 200 }), (n) => {
        let total = 0;
        for (let i = 0; i < n; i++) {
          const d = backoffMs(i);
          expect(d).toBeLessThanOrEqual(MAX);
          total += d;
        }
        expect(total).toBeLessThanOrEqual(MAX * n);
        expect(total).toBeGreaterThanOrEqual(MIN * n);
      }),
      RUNS,
    );
  });
});

// ---- Driving the real client with fakes ----

class FakeWs implements WsLike {
  static all: FakeWs[] = [];
  onopen: ((ev: Event) => unknown) | null = null;
  onclose: ((ev: CloseEvent) => unknown) | null = null;
  onmessage: ((ev: MessageEvent) => unknown) | null = null;
  onerror: ((ev: Event) => unknown) | null = null;
  constructor(public url: string) {
    FakeWs.all.push(this);
  }
  send() {}
  close() {}
}

class FakeTarget {
  visibilityState = "visible";
  private fns = new Map<string, Set<() => void>>();
  addEventListener(t: string, fn: () => void) {
    if (!this.fns.has(t)) this.fns.set(t, new Set());
    this.fns.get(t)!.add(fn);
  }
  removeEventListener(t: string, fn: () => void) {
    this.fns.get(t)?.delete(fn);
  }
  fire(t: string) {
    for (const fn of [...(this.fns.get(t) ?? [])]) fn();
  }
}

const recording = JSON.stringify({
  type: "recording",
  ts: 1730000000,
  indicator: "Recording (alarm)",
  stored_samples: 1,
  fault: null,
});

type Action =
  | { kind: "close"; code: number } // server/network close (never 4401)
  | { kind: "message" } // first message on the socket resets the attempt counter
  | { kind: "online" }; // immediate reconnect, resets the attempt counter

const arbCloseCode = fc.oneof(
  fc.constantFrom(1000, 1001, 1006, 1011, 4000, 4400, 4402),
  fc.integer({ min: 1000, max: 4999 }).filter((c) => c !== 4401),
);
const arbAction: fc.Arbitrary<Action> = fc.oneof(
  { weight: 6, arbitrary: arbCloseCode.map((code) => ({ kind: "close" as const, code })) },
  { weight: 1, arbitrary: fc.constant({ kind: "message" as const }) },
  { weight: 1, arbitrary: fc.constant({ kind: "online" as const }) },
);

describe("Property 19 (client): every scheduled reconnect delay is within bounds", () => {
  it("for random close/message/online sequences, delays are in [500, 5000] and follow backoffMs", () => {
    fc.assert(
      fc.property(fc.array(arbAction, { minLength: 1, maxLength: 60 }), (actions) => {
        FakeWs.all = [];
        const timers: { fn: () => void; ms: number; id: number; cleared: boolean }[] = [];
        let nextId = 1;
        const doc = new FakeTarget();
        const win = new FakeTarget();
        const client = createWsClient("wss://hub/ws", "tok", () => {}, () => {}, {
          WebSocket: FakeWs,
          setTimeout: (fn, ms) => {
            const t = { fn, ms, id: nextId++, cleared: false };
            timers.push(t);
            return t.id;
          },
          clearTimeout: (h) => {
            const t = timers.find((x) => x.id === h);
            if (t) t.cleared = true;
          },
          document: doc,
          window: win,
          now: () => 0,
        });
        const pending = () => timers.filter((t) => !t.cleared);
        const last = () => FakeWs.all[FakeWs.all.length - 1]!;

        client.start();
        let expectedAttempt = 0; // model of consecutive failures since last reset
        let gotMessage = false;
        const delays: number[] = [];

        for (const a of actions) {
          if (a.kind === "close") {
            last().onclose?.({ code: a.code } as CloseEvent);
            const p = pending();
            expect(p).toHaveLength(1);
            const ms = p[0]!.ms;
            delays.push(ms);
            expect(ms).toBeGreaterThanOrEqual(MIN);
            expect(ms).toBeLessThanOrEqual(MAX);
            expect(ms).toBe(backoffMs(expectedAttempt));
            expectedAttempt++;
            // Fire the retry so a fresh socket exists for the next action.
            p[0]!.cleared = true;
            p[0]!.fn();
            gotMessage = false;
          } else if (a.kind === "message") {
            last().onopen?.({} as Event);
            last().onmessage?.({ data: recording } as MessageEvent);
            if (!gotMessage) expectedAttempt = 0;
            gotMessage = true;
          } else {
            win.fire("online");
            expect(pending()).toHaveLength(0);
            expectedAttempt = 0;
            gotMessage = false;
          }
        }

        // Non-decreasing between resets; total bounded by 5000 per failure.
        const total = delays.reduce((s, d) => s + d, 0);
        expect(total).toBeLessThanOrEqual(MAX * delays.length);
        client.stop();
        expect(pending()).toHaveLength(0);
      }),
      RUNS,
    );
  });
});
