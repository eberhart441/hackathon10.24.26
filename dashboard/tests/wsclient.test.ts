// Example tests for the WS client and backoff (Req 7.3–7.5).
import { describe, expect, it } from "vitest";
import { backoffMs } from "../src/ws/backoff";
import { createWsClient, type WsLike, type WsStatus } from "../src/ws/client";
import type { HubMessage } from "../src/ws/messages";

const recording = JSON.stringify({
  type: "recording",
  ts: 1730000000,
  indicator: "Recording (alarm)",
  stored_samples: 1,
  fault: null,
});

class FakeWs implements WsLike {
  static all: FakeWs[] = [];
  sent: string[] = [];
  closed = false;
  onopen: ((ev: Event) => unknown) | null = null;
  onclose: ((ev: CloseEvent) => unknown) | null = null;
  onmessage: ((ev: MessageEvent) => unknown) | null = null;
  onerror: ((ev: Event) => unknown) | null = null;
  constructor(public url: string) {
    FakeWs.all.push(this);
  }
  send(d: string) {
    this.sent.push(d);
  }
  close() {
    this.closed = true;
  }
  // Test drivers
  open() {
    this.onopen?.({} as Event);
  }
  msg(data: unknown) {
    this.onmessage?.({ data } as MessageEvent);
  }
  serverClose(code: number) {
    this.onclose?.({ code } as CloseEvent);
  }
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

function setup(token: string | (() => string | null) = "tok") {
  FakeWs.all = [];
  const timers: { fn: () => void; ms: number; id: number; cleared: boolean }[] = [];
  let nextId = 1;
  const doc = new FakeTarget();
  const win = new FakeTarget();
  const messages: HubMessage[] = [];
  const discards: unknown[] = [];
  const statuses: WsStatus[] = [];
  let authFails = 0;
  const client = createWsClient("wss://hub/ws", token, (m) => messages.push(m), () => authFails++, {
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
    now: () => 42,
    onDiscard: (raw) => discards.push(raw),
    onStatus: (s) => statuses.push(s),
  });
  const pending = () => timers.filter((t) => !t.cleared);
  const runTimer = () => {
    const t = pending()[0]!;
    t.cleared = true;
    t.fn();
    return t.ms;
  };
  const last = () => FakeWs.all[FakeWs.all.length - 1]!;
  return { client, doc, win, messages, discards, statuses, pending, runTimer, last, authFails: () => authFails };
}

describe("backoffMs", () => {
  it("doubles from 500 ms and caps at 5000 ms", () => {
    expect([0, 1, 2, 3, 4, 5, 50].map(backoffMs)).toEqual([500, 1000, 2000, 4000, 5000, 5000, 5000]);
  });
  it("is robust to negative, fractional, NaN and huge attempts", () => {
    expect(backoffMs(-3)).toBe(500);
    expect(backoffMs(1.7)).toBe(1000);
    expect(backoffMs(Number.NaN)).toBe(500);
    expect(backoffMs(Number.POSITIVE_INFINITY)).toBe(5000);
    expect(backoffMs(1e308)).toBe(5000);
  });
});

describe("createWsClient", () => {
  it("sends the auth frame first on open and only that frame", () => {
    const h = setup("secret");
    h.client.start();
    expect(h.client.status()).toBe("connecting");
    h.last().open();
    expect(h.last().sent).toEqual([JSON.stringify({ type: "auth", token: "secret" })]);
    h.last().msg(recording);
    expect(h.client.status()).toBe("open");
    expect(h.messages).toHaveLength(1);
    // Never sends trigger_alarm or end_incident.
    for (const s of h.last().sent) expect(s).not.toMatch(/trigger_alarm|end_incident/);
  });

  it("reads the token lazily from a getter", () => {
    let t: string | null = "a";
    const h = setup(() => t);
    h.client.start();
    t = "b";
    h.last().open();
    expect(JSON.parse(h.last().sent[0]!)).toEqual({ type: "auth", token: "b" });
  });

  it("on close 4401 calls onAuthFail and does not retry", () => {
    const h = setup();
    h.client.start();
    h.last().open();
    h.last().serverClose(4401);
    expect(h.authFails()).toBe(1);
    expect(h.pending()).toHaveLength(0);
    expect(FakeWs.all).toHaveLength(1);
    // Visibility no longer triggers a reconnect after auth failure.
    h.doc.fire("visibilitychange");
    expect(FakeWs.all).toHaveLength(1);
  });

  it("retries with the backoff sequence and resets on the first message", () => {
    const h = setup();
    h.client.start();
    const delays: number[] = [];
    for (let i = 0; i < 6; i++) {
      h.last().serverClose(1006);
      expect(h.client.status()).toBe("reconnecting");
      delays.push(h.runTimer());
    }
    expect(delays).toEqual([500, 1000, 2000, 4000, 5000, 5000]);
    expect(FakeWs.all).toHaveLength(7);
    h.last().open();
    h.last().msg(recording);
    expect(h.client.status()).toBe("open");
    h.last().serverClose(1006);
    expect(h.runTimer()).toBe(500);
  });

  it("reconnects immediately on visible or online and reports reconnecting until a message", () => {
    const h = setup();
    h.client.start();
    h.last().open();
    h.last().msg(recording);
    const first = h.last();

    h.doc.visibilityState = "hidden";
    h.doc.fire("visibilitychange");
    expect(FakeWs.all).toHaveLength(1);

    h.doc.visibilityState = "visible";
    h.doc.fire("visibilitychange");
    expect(first.closed).toBe(true);
    expect(FakeWs.all).toHaveLength(2);
    expect(h.client.status()).toBe("reconnecting");
    // Late close from the old socket must not schedule a retry.
    first.serverClose(1000);
    expect(h.pending()).toHaveLength(0);

    h.last().open();
    expect(h.client.status()).toBe("reconnecting");
    h.last().msg(recording);
    expect(h.client.status()).toBe("open");

    h.win.fire("online");
    expect(FakeWs.all).toHaveLength(3);
    expect(h.client.status()).toBe("reconnecting");
    expect(h.statuses).toEqual(["open", "reconnecting", "open", "reconnecting"]);
  });

  it("passes unparseable frames to onDiscard and not to onMessage", () => {
    const h = setup();
    h.client.start();
    h.last().open();
    h.last().msg("{not json");
    h.last().msg(JSON.stringify({ type: "recording", ts: "x" }));
    expect(h.discards).toEqual(["{not json", JSON.stringify({ type: "recording", ts: "x" })]);
    expect(h.messages).toHaveLength(0);
    expect(h.client.status()).toBe("connecting");
  });

  it("stop closes the socket and cancels retries", () => {
    const h = setup();
    h.client.start();
    h.last().serverClose(1006);
    h.client.stop();
    expect(h.pending()).toHaveLength(0);
    h.win.fire("online");
    expect(FakeWs.all).toHaveLength(1);
  });
});
