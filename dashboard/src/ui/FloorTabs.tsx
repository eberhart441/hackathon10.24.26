// Floor tabs: one button per floor, 1 tap switches (Req 11.4, 19.1).
import type { SceneModel } from "../scene/model";
import { STRINGS } from "../scene/strings";

interface Props {
  tabs: SceneModel["floorTabs"];
  current: string;
  onSelect: (floorId: string) => void;
}

export function FloorTabs({ tabs, current, onSelect }: Props) {
  return (
    <nav aria-label={STRINGS.floor} style={{ display: "flex", gap: 4, overflowX: "auto" }}>
      {tabs.map((t) => (
        <button
          key={t.floorId}
          type="button"
          aria-pressed={t.floorId === current}
          aria-label={`${STRINGS.floor} ${t.name}, ${t.attention}, ${STRINGS.crew} ${t.crew}`}
          onClick={() => onSelect(t.floorId)}
          style={{
            minWidth: 56,
            minHeight: 56,
            padding: "0 12px",
            fontWeight: t.floorId === current ? 700 : 400,
            border: t.floorId === current ? "3px solid #000" : "1px solid #666",
          }}
        >
          {t.name} •{t.attention} · {STRINGS.crew} {t.crew}
        </button>
      ))}
    </nav>
  );
}
