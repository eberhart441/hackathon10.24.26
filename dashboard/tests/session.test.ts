import { describe, expect, it } from "vitest";
import { createSession, TOKEN_KEY, type StorageLike } from "../src/auth/session";
import type { FetchLike } from "../src/api/http";

interface Call {
  url: string;
  init: RequestInit | undefined;
}

type Route = (init: RequestInit | undefined) => { status: number; body?: unknown } | "network";

function fakeFetch(routes: Record<string, Route>): { fetch: FetchLike; calls: Call[] } {
  const calls: Call[] = [];
  const fetch: FetchLike = async (url, init) => {
    calls.push({ url, init });
    const key = `${init?.method ?? "GET"} ${url}`;
    const route = routes[key];
    if (!route) return new Response(JSON.stringify({ error: "not_found" }), { status: 404 });
    const r = route(init);
    if (r === "network") throw new TypeError("Failed to fetch");
    return new Response(r.body === undefined ? null : JSON.stringify(r.body), { status: r.status });
  };
  return { fetch, calls };
}

function recordingStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  const writes: string[] = [];
  const reads: string[] = [];
  const removes: string[] = [];
  const storage: StorageLike = {
    getItem: (k) => {
      reads.push(k);
      return data.get(k) ?? null;
    },
    setItem: (k, v) => {
      writes.push(k);
      data.set(k, v);
    },
    removeItem: (k) => {
      removes.push(k);
      data.delete(k);
    },
  };
  return { storage, data, writes, reads, removes };
}

function authHeader(init: RequestInit | undefined): string | undefined {
  return (init?.headers as Record<string, string> | undefined)?.Authorization;
}

describe("session startup", () => {
  it("laptop path keeps the local token in memory and touches no storage", async () => {
    const { fetch, calls } = fakeFetch({
      "POST /api/local/token": () => ({ status: 200, body: { token: "laptop-tok" } }),
      "GET /api/whoami": () => ({ status: 200, body: { laptop: true } }),
    });
    const s = recordingStorage();
    const session = createSession({ fetch, storage: s.storage });
    expect(await session.start()).toEqual({ kind: "laptop", token: "laptop-tok" });
    expect(s.writes).toEqual([]);
    expect(s.reads).toEqual([]);
    expect(s.data.size).toBe(0);
    const who = calls.find((c) => c.url === "/api/whoami");
    expect(authHeader(who?.init)).toBe("Bearer laptop-tok");
    expect(calls.every((c) => c.init?.cache === "no-store")).toBe(true);
  });

  it("phone path reads roomsense.token and sends it to whoami", async () => {
    const { fetch, calls } = fakeFetch({
      "POST /api/local/token": () => ({ status: 403, body: { error: "forbidden" } }),
      "GET /api/whoami": () => ({ status: 200, body: { laptop: false } }),
    });
    const s = recordingStorage({ [TOKEN_KEY]: "phone-tok" });
    const session = createSession({ fetch, storage: s.storage });
    expect(await session.start()).toEqual({ kind: "phone", token: "phone-tok" });
    expect(s.reads).toEqual([TOKEN_KEY]);
    expect(s.writes).toEqual([]);
    expect(authHeader(calls.find((c) => c.url === "/api/whoami")?.init)).toBe("Bearer phone-tok");
  });

  it("phone with no stored token needs pairing without calling whoami", async () => {
    const { fetch, calls } = fakeFetch({
      "POST /api/local/token": () => ({ status: 403 }),
    });
    const session = createSession({ fetch, storage: recordingStorage().storage });
    expect(await session.start()).toEqual({ kind: "needs_pair" });
    expect(calls.some((c) => c.url === "/api/whoami")).toBe(false);
  });

  it("401 on whoami → needs_pair and clears the stored token", async () => {
    const { fetch } = fakeFetch({
      "POST /api/local/token": () => ({ status: 403 }),
      "GET /api/whoami": () => ({ status: 401, body: { error: "unauthorized" } }),
    });
    const s = recordingStorage({ [TOKEN_KEY]: "revoked" });
    const session = createSession({ fetch, storage: s.storage });
    expect(await session.start()).toEqual({ kind: "needs_pair" });
    expect(s.removes).toEqual([TOKEN_KEY]);
    expect(s.data.has(TOKEN_KEY)).toBe(false);
    expect(session.token()).toBeNull();
  });
});

describe("pairWithCode", () => {
  it("stores only roomsense.token on success", async () => {
    const { fetch, calls } = fakeFetch({
      "POST /api/pair": () => ({ status: 200, body: { token: "new-tok" } }),
    });
    const s = recordingStorage();
    const session = createSession({ fetch, storage: s.storage });
    const r = await session.pairWithCode("123456");
    expect(r).toEqual({ ok: true, session: { kind: "phone", token: "new-tok" } });
    expect(s.writes).toEqual([TOKEN_KEY]);
    expect(s.data.get(TOKEN_KEY)).toBe("new-tok");
    expect(session.token()).toBe("new-tok");
    const call = calls[0];
    expect(call?.init?.body).toBe(JSON.stringify({ code: "123456" }));
    expect(authHeader(call?.init)).toBeUndefined();
  });

  it("429 surfaces as rate_limited, distinct from a wrong code", async () => {
    let status = 401;
    const { fetch } = fakeFetch({ "POST /api/pair": () => ({ status, body: { error: "x" } }) });
    const s = recordingStorage();
    const session = createSession({ fetch, storage: s.storage });
    expect(await session.pairWithCode("000000")).toEqual({ ok: false, reason: "wrong_code" });
    status = 429;
    expect(await session.pairWithCode("000000")).toEqual({ ok: false, reason: "rate_limited" });
    expect(s.writes).toEqual([]);
  });

  it("rejects non-6-digit input without a request", async () => {
    const { fetch, calls } = fakeFetch({});
    const session = createSession({ fetch, storage: recordingStorage().storage });
    expect(await session.pairWithCode("12a45")).toEqual({ ok: false, reason: "invalid_format" });
    expect(calls).toHaveLength(0);
  });

  it("network failure surfaces as network", async () => {
    const { fetch } = fakeFetch({ "POST /api/pair": () => "network" });
    const session = createSession({ fetch, storage: recordingStorage().storage });
    expect(await session.pairWithCode("123456")).toEqual({ ok: false, reason: "network" });
  });
});
