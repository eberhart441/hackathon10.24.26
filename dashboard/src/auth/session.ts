// Session startup and token storage (Req 1.5, 2.7–2.9, 17.4).
//
// Startup (design "Startup and pairing sequence"):
//   1. POST /api/local/token. 200 → laptop; the token lives in memory only and
//      is NEVER written to storage.
//   2. Otherwise read localStorage["roomsense.token"]; none → needs_pair.
//   3. GET /api/whoami with the token. 401 → clear the stored token, needs_pair.
//
// The ONLY storage key this app ever writes is `roomsense.token` (Req 17.4).
// No sessionStorage, IndexedDB, or Cache API use anywhere in this module.
import { createHubApi, type FetchLike, type HubApi } from "../api/http";

export const TOKEN_KEY = "roomsense.token";

export type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export type Session =
  | { kind: "laptop"; token: string }
  | { kind: "phone"; token: string }
  | { kind: "needs_pair" };

export type PairResult =
  | { ok: true; session: { kind: "phone"; token: string } }
  | { ok: false; reason: "invalid_format" | "wrong_code" | "rate_limited" | "network" | "error" };

export interface SessionDeps {
  fetch?: FetchLike;
  /** Defaults to window.localStorage (null if unavailable). */
  storage?: StorageLike | null;
  baseUrl?: string;
}

export interface SessionManager {
  start(): Promise<Session>;
  pairWithCode(code: string): Promise<PairResult>;
  /** Drop the token (on HTTP 401 or WS close 4401). */
  clearToken(): void;
  /** Current token (memory), or null. */
  token(): string | null;
  /** Hub API bound to the current token. */
  readonly api: HubApi;
}

function defaultStorage(): StorageLike | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null; // storage access can throw (e.g. blocked in some private modes)
  }
}

export function createSession(deps: SessionDeps = {}): SessionManager {
  const storage = deps.storage !== undefined ? deps.storage : defaultStorage();
  let current: string | null = null;
  let isLaptopToken = false;

  const httpDeps: Parameters<typeof createHubApi>[0] = { getToken: () => current };
  if (deps.fetch) httpDeps.fetch = deps.fetch;
  if (deps.baseUrl !== undefined) httpDeps.baseUrl = deps.baseUrl;
  const api = createHubApi(httpDeps);

  function readStored(): string | null {
    try {
      const t = storage?.getItem(TOKEN_KEY) ?? null;
      return t && t.length > 0 ? t : null;
    } catch {
      return null;
    }
  }

  function clearToken(): void {
    if (!isLaptopToken) {
      try {
        storage?.removeItem(TOKEN_KEY);
      } catch {
        /* ignore */
      }
    }
    current = null;
    isLaptopToken = false;
  }

  async function start(): Promise<Session> {
    const local = await api.localToken();
    if (local.ok) {
      current = local.data.token;
      isLaptopToken = true;
    } else {
      current = readStored();
      isLaptopToken = false;
      if (current === null) return { kind: "needs_pair" };
    }
    const token = current;
    const who = await api.whoami(token);
    if (!who.ok) {
      if (who.kind === "unauthorized") {
        clearToken();
        return { kind: "needs_pair" };
      }
      // Hub unreachable or transient error: keep the token; the WS client retries.
      return isLaptopToken ? { kind: "laptop", token } : { kind: "phone", token };
    }
    return who.data.laptop ? { kind: "laptop", token } : { kind: "phone", token };
  }

  async function pairWithCode(code: string): Promise<PairResult> {
    const trimmed = code.trim();
    if (!/^\d{6}$/.test(trimmed)) return { ok: false, reason: "invalid_format" };
    const res = await api.pair(trimmed);
    if (!res.ok) {
      switch (res.kind) {
        case "unauthorized":
          return { ok: false, reason: "wrong_code" };
        case "rate_limited":
          return { ok: false, reason: "rate_limited" };
        case "network":
          return { ok: false, reason: "network" };
        default:
          return { ok: false, reason: "error" };
      }
    }
    const token = res.data.token;
    try {
      storage?.setItem(TOKEN_KEY, token);
    } catch {
      /* storage unavailable: token stays in memory for this run */
    }
    current = token;
    isLaptopToken = false;
    return { ok: true, session: { kind: "phone", token } };
  }

  return { start, pairWithCode, clearToken, token: () => current, api };
}
