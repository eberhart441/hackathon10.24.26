import { applyMessage, type Store } from '../store';
import { parseMessage } from './parse';

const BACKOFF_START_MS = 500;
const BACKOFF_MAX_MS = 5000;
const AUTH_FAILED = 4401;

// Opens /ws, authenticates with the first message, and keeps reconnecting (Kiro R7.3–R7.5).
export class WsClient {
  private ws: WebSocket | null = null;
  private backoff = BACKOFF_START_MS;
  private timer: number | undefined;
  private stopped = false;

  constructor(
    private store: Store,
    private getToken: () => string | null,
    private onAuthFailed: () => void,
  ) {
    document.addEventListener('visibilitychange', this.onWake);
    window.addEventListener('online', this.onWake);
  }

  start() {
    this.stopped = false;
    this.open();
  }

  stop() {
    this.stopped = true;
    window.clearTimeout(this.timer);
    document.removeEventListener('visibilitychange', this.onWake);
    window.removeEventListener('online', this.onWake);
    this.ws?.close();
    this.ws = null;
  }

  send(msg: unknown) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  // iOS suspends a backgrounded PWA and leaves a dead socket behind, so always reopen on wake.
  private onWake = () => {
    if (this.stopped || document.visibilityState !== 'visible') return;
    this.store.update((s) => ({ ...s, reconnecting: true }));
    window.clearTimeout(this.timer);
    this.backoff = BACKOFF_START_MS;
    this.ws?.close();
    this.open();
  };

  private open() {
    const token = this.getToken();
    if (!token) return;
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${location.host}/ws`);
    this.ws = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token }));
    ws.onmessage = (ev) => {
      const msg = parseMessage(ev.data);
      if (!msg) {
        this.store.update((s) => ({ ...s, discarded: s.discarded + 1 }));
        return;
      }
      this.backoff = BACKOFF_START_MS;
      this.store.update((s) => applyMessage(s, msg, Date.now()));
    };
    ws.onclose = (ev) => {
      if (this.ws !== ws) return;
      this.ws = null;
      if (ev.code === AUTH_FAILED) {
        this.onAuthFailed();
        return;
      }
      if (this.stopped) return;
      this.timer = window.setTimeout(() => this.open(), this.backoff);
      this.backoff = Math.min(this.backoff * 2, BACKOFF_MAX_MS);
    };
  }
}
