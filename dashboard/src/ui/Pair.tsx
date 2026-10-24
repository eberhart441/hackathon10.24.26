// In-app pairing keypad (Req 2.8, 2.9, 10.1, 19.1). No <input>, so no OS keyboard.
import { useState } from "preact/hooks";
import type { PairResult, SessionManager } from "../auth/session";
import { COLORS } from "../scene/palette";
import { STRINGS } from "../scene/strings";

type Paired = Extract<PairResult, { ok: true }>["session"];

const KEY = { minWidth: 56, minHeight: 56, fontSize: 24, borderRadius: 8 } as const;

export function Pair(props: { session: SessionManager; onPaired: (s: Paired) => void; notice?: string }) {
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<string | null>(props.notice ?? null);
  const [busy, setBusy] = useState(false);

  async function press(d: string) {
    if (busy || code.length >= 6) return;
    const next = code + d;
    setCode(next);
    if (next.length < 6) return;
    setBusy(true);
    const r = await props.session.pairWithCode(next);
    setBusy(false);
    if (r.ok) return props.onPaired(r.session);
    setCode("");
    setMsg(r.reason === "wrong_code" ? STRINGS.pairWrongCode
      : r.reason === "rate_limited" ? STRINGS.pairTooManyTries : STRINGS.pairNetwork);
  }

  return (
    <main style={{ minHeight: "100dvh", padding: 16, background: COLORS.background, color: COLORS.text, textAlign: "center" }}>
      <p role="note">{STRINGS.disclaimer}</p>
      <h1>{STRINGS.pairTitle}</h1>
      <p>{STRINGS.pairPrompt}</p>
      <div aria-live="polite" style={{ fontSize: 36, letterSpacing: 12, margin: "16px 0", fontFamily: "monospace" }}>
        {code.padEnd(6, "•")}
      </div>
      {msg && <p role="alert">{msg}</p>}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 72px)", gap: 8, justifyContent: "center" }}>
        {["1", "2", "3", "4", "5", "6", "7", "8", "9"].map((d) => (
          <button key={d} type="button" style={KEY} disabled={busy} onClick={() => void press(d)}>{d}</button>
        ))}
        <button type="button" style={KEY} disabled={busy} onClick={() => setCode(code.slice(0, -1))}>{STRINGS.pairDelete}</button>
        <button type="button" style={KEY} disabled={busy} onClick={() => void press("0")}>0</button>
      </div>
    </main>
  );
}
