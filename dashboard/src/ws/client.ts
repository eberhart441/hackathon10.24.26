// Hub WebSocket client (Req 7.3–7.5).
// - Sends {"type":"auth","token":...} as the first frame on open.
// - Close code 4401 → onAuthFail, no retry.
// - Other closes → retry after backoffMs(attempt++); attempt resets on the first message.
// - visibilitychange → visible, or online → close and reconnect now; status is
//   "reconnecting" until the first message arrives (iOS drops background sockets).
// The only frame this client ever sends is the auth frame: it never sends
// trigger_alarm or end_incident (those stay on the laptop via REST).

import { backoffMs } from "./backoff";
import { parseMessage, type HubMessage } from "./messages";

export type WsStatus = "connecting" | "open" | "reconnecting";

export interface WsClient {
  start(): void;
  stop(): void;
  status(): WsStatus;
}

/** Minimal WebSocket surface the client uses; the browser WebSocket satisfies it. */
export interface WsLike {
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((ev: Event) => unknown) | null;
  onclose: ((ev: CloseEvent) => unknown) | null;
  onmessage: ((ev: MessageEvent) => unknown) | null;
  onerror: ((ev: Event) => unknown) | null;
}

export type WsCtor = new (url: string) => WsLike;

interface EventTargetLike {
  addEventListener(type: string, fn: () => void): void;
  removeEventListener(type: string, fn: () => void): void;
}

export interface DocumentLike extends EventTargetLike {
  readonly visibilityState: string;
}

export interface WsClientDeps {
  WebSocket?: WsCtor;
  setTimeout?: (fn: () => void, ms: number) => unknown;
  clearTimeout?: (handle: unknown) => void;
  document?: DocumentLike;
  window?: EventTargetLike;
  /** Receipt-time clock in ms. */
  now?: () => number;
  /** Called with each raw frame that fails parsing (Store counts discards, Req 7.2). */
  onDiscard?: (raw: unknown) => void;
  /** Called whenever status() changes. */
  onStatus?: (s: WsStatus) => void;
}

export const AUTH_FAIL_CODE = 4401;

export function createWsClient(
  url: string,
  token: string | (() => string | null),
  onMessage: (m: HubMessage, receivedAt: number) => void,
  onAuthFail: () => void,
  deps: WsClientDeps = {},
): WsClient {
  const Ctor: WsCtor = deps.WebSocket ?? (globalThis.WebSocket as unknown as WsCtor);
  const setT = deps.setTimeout ?? ((fn: () => void, ms: number) => globalThis.setTimeout(fn, ms));
  const clearT =
    deps.clearTimeout ?? ((h: unknown) => globalThis.clearTimeout(h as ReturnType<typeof setTimeout>));
  const doc: DocumentLike | undefined = deps.document ?? (typeof document !== "undefined" ? document : undefined);
  const win: EventTargetLike | undefined = deps.window ?? (typeof window !== "undefined" ? window : undefined);
  const now = deps.now ?? (() => Date.now());

  let sock: WsLike | null = null;
  let retry: unknown = null;
  let attempt = 0;
  let running = false;
  let gotMessage = false; // first message received on the current socket
  let st: WsStatus = "connecting";

  const setStatus = (s: WsStatus): void => {
    if (s === st) return;
    st = s;
    deps.onStatus?.(s);
  };

  const readToken = (): string | null => (typeof token === "function" ? token() : token);

  const clearRetry = (): void => {
    if (retry !== null) {
      clearT(retry);
      retry = null;
    }
  };

  // Detach handlers first so the old socket's close event cannot schedule a retry.
  const dropSocket = (): void => {
    const s = sock;
    sock = null;
    if (!s) return;
    s.onopen = s.onclose = s.onmessage = s.onerror = null;
    try {
      s.close();
    } catch {
      // Already closed or closing; nothing to do.
    }
  };

  const authFail = (): void => {
    running = false;
    clearRetry();
    dropSocket();
    detach();
    onAuthFail();
  };

  const connect = (): void => {
    retry = null;
    if (!running) return;
    gotMessage = false;
    const s = new Ctor(url);
    sock = s;

    s.onopen = () => {
      if (sock !== s) return;
      const t = readToken();
      if (t === null) {
        authFail();
        return;
      }
      s.send(JSON.stringify({ type: "auth", token: t }));
    };

    s.onmessage = (ev: MessageEvent) => {
      if (sock !== s) return;
      const receivedAt = now();
      const raw: unknown = ev.data;
      const msg = typeof raw === "string" ? parseMessage(raw) : null;
      if (msg === null) {
        deps.onDiscard?.(raw);
        return;
      }
      if (!gotMessage) {
        gotMessage = true;
        attempt = 0;
        setStatus("open");
      }
      onMessage(msg, receivedAt);
    };

    s.onclose = (ev: CloseEvent) => {
      if (sock !== s) return;
      sock = null;
      if (ev.code === AUTH_FAIL_CODE) {
        authFail();
        return;
      }
      if (!running) return;
      setStatus("reconnecting");
      const delay = backoffMs(attempt);
      attempt = Math.min(attempt + 1, 1000);
      retry = setT(connect, delay);
    };

    // Errors are always followed by a close event; the close handler retries.
    s.onerror = () => {};
  };

  const reconnectNow = (): void => {
    if (!running) return;
    clearRetry();
    dropSocket();
    attempt = 0;
    setStatus("reconnecting");
    connect();
  };

  const onVisibility = (): void => {
    if (doc && doc.visibilityState === "visible") reconnectNow();
  };
  const onOnline = (): void => reconnectNow();

  function detach(): void {
    doc?.removeEventListener("visibilitychange", onVisibility);
    win?.removeEventListener("online", onOnline);
  }

  return {
    start() {
      if (running) return;
      running = true;
      attempt = 0;
      setStatus("connecting");
      doc?.addEventListener("visibilitychange", onVisibility);
      win?.addEventListener("online", onOnline);
      connect();
    },
    stop() {
      if (!running) return;
      running = false;
      clearRetry();
      dropSocket();
      detach();
    },
    status: () => st,
  };
}
