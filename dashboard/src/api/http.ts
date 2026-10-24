// Hub HTTP wrapper (Req 1.5, 2.7–2.9).
// - Adds `Authorization: Bearer <token>` when a token is available.
// - Always `cache: "no-store"`: no /api/* response is ever cached (Req 17.2).
// - Maps statuses to typed results: 401 → "unauthorized" (show Pair screen),
//   403 → "forbidden" (laptop-only route from a phone), 429 → "rate_limited",
//   404 → "not_found", network failure → "network".
// This module never touches storage; token persistence lives in auth/session.ts.

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export type HttpErrorKind =
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "rate_limited"
  | "http_error"
  | "network";

export type HttpResult<T> =
  | { ok: true; data: T }
  | { ok: false; kind: HttpErrorKind; status?: number; error?: string };

export interface TokenResponse {
  token: string;
}
export interface WhoamiResponse {
  laptop: boolean;
}
export interface PairingCodeResponse {
  code: string;
  expires_in_s: number;
}
export interface SystemStateResponse {
  system_state: string;
}
export interface TriggerAlarmResponse extends SystemStateResponse {
  simulated: boolean;
}
export interface SearchedResponse {
  room_id: string;
  searched: boolean;
}

export interface HttpDeps {
  fetch?: FetchLike;
  /** Prefix for every path, e.g. "" (same origin) or "https://192.168.137.1:8443". */
  baseUrl?: string;
  /** Returns the current token, or null when none is held. */
  getToken?: () => string | null;
}

export interface HubApi {
  pair(code: string): Promise<HttpResult<TokenResponse>>;
  localToken(): Promise<HttpResult<TokenResponse>>;
  whoami(token?: string): Promise<HttpResult<WhoamiResponse>>;
  pairingCode(): Promise<HttpResult<PairingCodeResponse>>;
  revokePhones(): Promise<HttpResult<unknown>>;
  triggerAlarm(): Promise<HttpResult<TriggerAlarmResponse>>;
  endIncident(): Promise<HttpResult<SystemStateResponse>>;
  markSearched(roomId: string): Promise<HttpResult<SearchedResponse>>;
}

function kindForStatus(status: number): HttpErrorKind {
  switch (status) {
    case 401:
      return "unauthorized";
    case 403:
      return "forbidden";
    case 404:
      return "not_found";
    case 429:
      return "rate_limited";
    default:
      return "http_error";
  }
}

async function readJson(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return undefined;
  }
}

function errorText(body: unknown): string | undefined {
  if (typeof body === "object" && body !== null && "error" in body) {
    const e = (body as { error: unknown }).error;
    if (typeof e === "string") return e;
  }
  return undefined;
}

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

type Check<T> = (body: unknown) => body is T;

const isToken: Check<TokenResponse> = (b): b is TokenResponse =>
  isObj(b) && typeof b.token === "string" && b.token.length > 0;
const isWhoami: Check<WhoamiResponse> = (b): b is WhoamiResponse =>
  isObj(b) && typeof b.laptop === "boolean";
const isPairingCode: Check<PairingCodeResponse> = (b): b is PairingCodeResponse =>
  isObj(b) && typeof b.code === "string" && typeof b.expires_in_s === "number";
const isSystemState: Check<SystemStateResponse> = (b): b is SystemStateResponse =>
  isObj(b) && typeof b.system_state === "string";
const isTrigger: Check<TriggerAlarmResponse> = (b): b is TriggerAlarmResponse =>
  isSystemState(b) && typeof (b as unknown as Record<string, unknown>).simulated === "boolean";
const isSearched: Check<SearchedResponse> = (b): b is SearchedResponse =>
  isObj(b) && typeof b.room_id === "string" && typeof b.searched === "boolean";
const isAny: Check<unknown> = (_b): _b is unknown => true;

export function createHubApi(deps: HttpDeps = {}): HubApi {
  const doFetch: FetchLike = deps.fetch ?? ((input, init) => globalThis.fetch(input, init));
  const base = deps.baseUrl ?? "";
  const getToken = deps.getToken ?? (() => null);

  async function request<T>(
    method: "GET" | "POST",
    path: string,
    check: Check<T>,
    opts: { body?: unknown; token?: string | null } = {},
  ): Promise<HttpResult<T>> {
    const headers: Record<string, string> = { Accept: "application/json" };
    const token = opts.token !== undefined ? opts.token : getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    const init: RequestInit = { method, headers, cache: "no-store", credentials: "omit" };
    if (opts.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    let res: Response;
    try {
      res = await doFetch(base + path, init);
    } catch {
      return { ok: false, kind: "network" };
    }
    const body = await readJson(res);
    if (!res.ok) {
      const error = errorText(body);
      const out: HttpResult<T> = { ok: false, kind: kindForStatus(res.status), status: res.status };
      if (error !== undefined) out.error = error;
      return out;
    }
    if (!check(body)) {
      return { ok: false, kind: "http_error", status: res.status, error: "bad_response" };
    }
    return { ok: true, data: body };
  }

  return {
    // /api/pair and /api/local/token need no token; never send a stale one.
    pair: (code) => request("POST", "/api/pair", isToken, { body: { code }, token: null }),
    localToken: () => request("POST", "/api/local/token", isToken, { token: null }),
    whoami: (token) => request("GET", "/api/whoami", isWhoami, token !== undefined ? { token } : {}),
    pairingCode: () => request("GET", "/api/local/pairing-code", isPairingCode),
    revokePhones: () => request("POST", "/api/local/revoke-phones", isAny),
    triggerAlarm: () => request("POST", "/api/alarm/trigger", isTrigger),
    endIncident: () => request("POST", "/api/incident/end", isSystemState),
    markSearched: (roomId) =>
      request("POST", `/api/rooms/${encodeURIComponent(roomId)}/searched`, isSearched),
  };
}
