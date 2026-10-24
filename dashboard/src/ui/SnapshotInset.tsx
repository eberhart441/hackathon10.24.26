// Alarm-time snapshot inset (Req 13.5, 13.6). Shown only in fire mode.
import { useState } from "preact/hooks";
import type { FloorPlan } from "../floorplan/types";
import type { SceneModel } from "../scene/model";
import { COLORS, STATE_PALETTE } from "../scene/palette";
import { STRINGS } from "../scene/strings";
import { labelFor } from "../ws/messages";

/** "inset" = small corner card, tap to enlarge; "toggle" = hidden behind an "At alarm" button. */
export const snapshotMode: "inset" | "toggle" = "inset";

const GREY = "#777777";

interface Props {
  plan: FloorPlan;
  floorId: string;
  scene: SceneModel;
  onSwap?: (enlarged: boolean) => void;
}

export function SnapshotInset({ plan, floorId, scene, onSwap }: Props) {
  const [open, setOpen] = useState(false);
  if (scene.mode !== "fire") return null;
  const floor = plan.floors.find((f) => f.id === floorId);
  if (floor === undefined) return null;

  const byId = new Map(scene.snapshot.map((s) => [s.roomId, s.treatment]));
  const pts = floor.rooms.flatMap((r) => r.polygon);
  const minX = Math.min(...pts.map((p) => p[0]));
  const minY = Math.min(...pts.map((p) => p[1]));
  const w = Math.max(...pts.map((p) => p[0])) - minX || 1;
  const h = Math.max(...pts.map((p) => p[1])) - minY || 1;

  const toggle = () => {
    setOpen(!open);
    onSwap?.(!open);
  };

  if (snapshotMode === "toggle" && !open) {
    return (
      <button type="button" onClick={toggle} style={{ position: "absolute", right: 8, bottom: 8, minHeight: 56, minWidth: 56, background: COLORS.furniture, color: COLORS.text, border: "1px solid #888" }}>
        {STRINGS.atAlarmToggle}
      </button>
    );
  }

  const size = open ? { width: "80vw", maxWidth: 640 } : { width: 160 };
  return (
    <figure
      role="button"
      tabIndex={0}
      aria-label={STRINGS.atAlarm}
      onClick={toggle}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && toggle()}
      style={{ position: "absolute", right: 8, bottom: 8, margin: 0, padding: 4, background: COLORS.background, color: COLORS.text, border: "2px solid #888", zIndex: 5, cursor: "pointer", ...size }}
    >
      <figcaption style={{ fontWeight: 700, fontSize: 12 }}>{STRINGS.atAlarm}</figcaption>
      <svg viewBox={`${minX - 0.2} ${-(minY + h) - 0.2} ${w + 0.4} ${h + 0.4}`} style={{ width: "100%", height: "auto", display: "block" }}>
        {floor.rooms.map((r) => {
          const t = byId.get(r.id) ?? null;
          const cx = r.polygon.reduce((a, p) => a + p[0], 0) / r.polygon.length;
          const cy = r.polygon.reduce((a, p) => a + p[1], 0) / r.polygon.length;
          return (
            <g key={r.id}>
              <polygon points={r.polygon.map((p) => `${p[0]},${-p[1]}`).join(" ")} fill={t === null ? GREY : STATE_PALETTE[t]} stroke={COLORS.text} strokeWidth={0.05} />
              <text x={cx} y={-cy} fontSize={Math.max(w, h) / 18} textAnchor="middle" dominantBaseline="middle" fill="#000" stroke="#fff" strokeWidth={0.04} paintOrder="stroke">
                {t === null ? STRINGS.none : labelFor(t)}
              </text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
