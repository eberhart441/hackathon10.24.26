// REST helpers. A phone keeps its token in localStorage under one key (Kiro R2.9, R17.4);
// the laptop gets a fresh in-memory token from the hub on every start.

const TOKEN_KEY = 'roomsense.token';

export class AuthError extends Error {}

let token: string | null = null;
let laptop = false;

export function getToken(): string | null {
  return token;
}

export function isLaptop(): boolean {
  return laptop;
}

function storedToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function storeToken(t: string | null) {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Private mode: the phone just has to pair again next launch.
  }
}

async function call<T>(method: string, path: string, body?: unknown, auth = true): Promise<T> {
  const headers: Record<string, string> = {};
  if (auth && token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store' });
  if (res.status === 401) throw new AuthError('Not paired');
  if (!res.ok) {
    let detail = `Hub returned ${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

// Returns true when a usable token is in hand; false means the phone must pair.
export async function ensureToken(): Promise<boolean> {
  // A network failure means the hub is unreachable (the caller shows "Hub not reachable" and
  // retries). Only a refusal means "this is not the laptop", so only then try the phone token.
  const local = await fetch('/api/local/token', { method: 'POST', cache: 'no-store' });
  if (local.ok) {
    token = (await local.json()).token;
    laptop = true;
    return true;
  }
  laptop = false;
  token = storedToken();
  return !!token;
}

export function forgetToken() {
  token = null;
  if (!laptop) storeToken(null);
}

export async function pair(code: string): Promise<void> {
  const res = await fetch('/api/pair', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
    cache: 'no-store',
  });
  if (res.status === 429) throw new Error('Too many tries. Wait a minute, then enter the new code from the laptop.');
  if (res.status === 401) throw new Error('That code is wrong or has expired. Check the laptop for the current code.');
  if (!res.ok) throw new Error(`Pairing failed (hub returned ${res.status}).`);
  token = (await res.json()).token;
  storeToken(token);
}

export const api = {
  whoami: () => call<{ loopback: boolean }>('GET', '/api/whoami'),
  floorplan: () => call<unknown>('GET', '/api/floorplan'),
  pairingCode: () => call<{ code: string; expires_in: number }>('GET', '/api/local/pairing-code'),
  revokePhones: () => call<{ revoked: boolean; closed_sockets: number }>('POST', '/api/local/revoke-phones'),
  triggerAlarm: () => call<{ system_state: string; simulated: boolean }>('POST', '/api/alarm/trigger'),
  endIncident: () => call<{ system_state: string }>('POST', '/api/incident/end'),
  markSearched: (roomId: string) => call<{ room_id: string; searched: boolean }>('POST', `/api/rooms/${encodeURIComponent(roomId)}/searched`),
};
