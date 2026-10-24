// Laptop-only controls (Req 1.4, 1.5, 5.3–5.6, 14.5). The app renders this only for a laptop session.
import { useEffect, useState } from "preact/hooks";
import type { HubApi } from "../api/http";
import { COLORS } from "../scene/palette";
import { STRINGS } from "../scene/strings";

const BTN = {
  minWidth: 56, minHeight: 56, padding: "0 12px", fontSize: "16px",
  background: COLORS.furniture, color: COLORS.text, border: `1px solid ${COLORS.text}`,
} as const;

interface Props {
  api: HubApi;
  fireMode: boolean;
  onTriggered: () => void;
}

export function LaptopControls({ api, fireMode, onTriggered }: Props) {
  const [confirm, setConfirm] = useState<"end" | "revoke" | null>(null);
  const [code, setCode] = useState<{ code: string; until: number } | null>(null);
  const [, tick] = useState(0);

  useEffect(() => {
    if (!code) return;
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [code]);

  const secs = code ? Math.max(0, Math.ceil((code.until - Date.now()) / 1000)) : 0;

  const pair = async () => {
    const r = await api.pairingCode();
    if (r.ok) setCode({ code: r.data.code, until: Date.now() + r.data.expires_in_s * 1000 });
  };
  const trigger = async () => {
    const r = await api.triggerAlarm();
    if (r.ok) onTriggered();
  };
  const doConfirm = async () => {
    const which = confirm;
    setConfirm(null);
    if (which === "end") await api.endIncident();
    if (which === "revoke") await api.revokePhones();
  };

  return (
    <section style={{ display: "flex", flexWrap: "wrap", gap: 8, padding: 8, alignItems: "center" }}>
      {!fireMode && <button type="button" style={BTN} onClick={trigger}>{STRINGS.triggerAlarm}</button>}
      {fireMode && <button type="button" style={BTN} onClick={() => setConfirm("end")}>{STRINGS.endIncident}</button>}
      <button type="button" style={BTN} onClick={pair}>{STRINGS.pairPhone}</button>
      {code && secs > 0 && (
        <span aria-live="polite">
          {STRINGS.pairCode}: <strong style={{ fontSize: "24px", letterSpacing: "0.2em" }}>{code.code}</strong> {secs}
          {STRINGS.secondsLeft}
        </span>
      )}
      <button type="button" style={BTN} onClick={() => setConfirm("revoke")}>{STRINGS.revokePhones}</button>
      {confirm && (
        <div role="dialog" style={{ position: "fixed", left: 0, right: 0, bottom: 0, background: COLORS.background,
          color: COLORS.text, borderTop: `2px solid ${COLORS.text}`, padding: 12, zIndex: 20 }}>
          <p>{confirm === "end" ? STRINGS.endIncidentConfirm : STRINGS.revokePhonesConfirm}</p>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" style={{ ...BTN, background: COLORS.alarmRed, fontWeight: 700 }} onClick={doConfirm}>
              {STRINGS.confirm}
            </button>
            <button type="button" style={BTN} onClick={() => setConfirm(null)}>{STRINGS.cancel}</button>
          </div>
        </div>
      )}
    </section>
  );
}
