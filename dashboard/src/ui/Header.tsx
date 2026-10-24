// Header: recording indicator, health chip + fault list, disclaimer, badges (Req 10.1–10.5, 11.6).
import { useEffect, useState } from "preact/hooks";
import type { SceneModel } from "../scene/model";
import type { HealthMsg } from "../ws/messages";
import { STRINGS } from "../scene/strings";
import { COLORS } from "../scene/palette";

const TOUCH = { minHeight: "56px", minWidth: "56px" };
const badge = { padding: "4px 8px", border: `2px solid ${COLORS.text}`, fontWeight: 700 };

export function Disclaimer() {
  return <p role="note" style={{ margin: "4px 0", fontSize: "14px" }}>{STRINGS.disclaimer}</p>;
}

export function HealthChip({ summary, health }: { summary: string | null; health: HealthMsg | null }) {
  const [open, setOpen] = useState(false);
  const faults = health ? health.nodes.filter((n) => n.status !== "ok") : [];
  const tags = health?.tag_faults ?? [];
  return (
    <div>
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}
        style={{ ...TOUCH, background: "transparent", color: COLORS.text, border: `2px solid ${COLORS.text}`, fontSize: "16px" }}>
        {summary ?? STRINGS.linkHealth}
      </button>
      {open && (
        <div role="region" aria-label={STRINGS.faultList}
          style={{ position: "absolute", right: 0, background: COLORS.background, border: `2px solid ${COLORS.text}`, padding: "8px", zIndex: 10, maxWidth: "90vw" }}>
          <strong>{STRINGS.faultList}</strong>
          {faults.length === 0 && tags.length === 0 && <p>{STRINGS.noFaults}</p>}
          <ul style={{ paddingLeft: "16px" }}>
            {faults.map((n) => (
              <li key={n.node_id}>
                {n.node_id} ({n.role}, {n.room_id}) — {n.status}
                {n.cause && <div>{STRINGS.faultCause}: {n.cause}</div>}
                {n.action && <div>{STRINGS.faultAction}: {n.action}</div>}
              </li>
            ))}
            {tags.map((t) => (
              <li key={t.tag_id}>
                {STRINGS.crew} {t.tag_id} {STRINGS.notHeard} {Math.round(t.silent_s)} s ({STRINGS.lastHeard}: {t.last_room})
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function Header({ header, health, simulatedTrigger, view2d }: {
  header: SceneModel["header"]; health: HealthMsg | null; simulatedTrigger: boolean; view2d?: boolean;
}) {
  useEffect(() => {
    let meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    if (!meta) {
      meta = document.createElement("meta");
      meta.name = "theme-color";
      document.head.appendChild(meta);
    }
    meta.content = header.alarm ? COLORS.alarmRed : COLORS.background;
  }, [header.alarm]);

  return (
    <header style={{ position: "relative", background: header.alarm ? COLORS.alarmRed : COLORS.background, color: COLORS.text, padding: "8px 12px" }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px", justifyContent: "space-between" }}>
        {header.recording && <span aria-live="polite" style={{ fontWeight: 700 }}>{header.recording}</span>}
        {header.simulatedData && <span style={badge}>{STRINGS.simulatedData}</span>}
        {simulatedTrigger && <span style={badge}>{STRINGS.simulatedTrigger}</span>}
        {view2d && <span style={badge}>{STRINGS.view2d}</span>}
        <HealthChip summary={header.health} health={health} />
      </div>
      <Disclaimer />
    </header>
  );
}
