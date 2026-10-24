// Priority list in server order, never re-sorted (Req 1.2, 1.3, 11.1, 11.2, 11.5, 11.7).
// Portrait: bottom sheet with 3 rows visible, expandable. Landscape / ≥900 px: side list.
import { useState } from "preact/hooks";
import type { RoomDescriptor, SceneModel } from "../scene/model";
import { STRINGS } from "../scene/strings";
import { COLORS } from "../scene/palette";

const BTN = { minWidth: 56, minHeight: 56, background: COLORS.furniture, color: COLORS.text, border: "1px solid #888" } as const;

/** 2-tap mark searched: ✓ arms, "Mark searched" confirms. No optimistic change. */
export function MarkSearched({ room, onMarkSearched }: { room: RoomDescriptor; onMarkSearched: (id: string) => void }) {
  const [armed, setArmed] = useState(false);
  if (room.searched) return <span>{STRINGS.searchedChip}</span>;
  if (!armed)
    return (
      <button type="button" style={BTN} aria-label={`${STRINGS.markSearched}: ${room.name}`} onClick={() => setArmed(true)}>
        ✓
      </button>
    );
  return (
    <span style={{ display: "flex", gap: 4 }}>
      <button
        type="button"
        style={{ ...BTN, fontWeight: 700 }}
        onClick={() => {
          setArmed(false);
          onMarkSearched(room.roomId);
        }}
      >
        {STRINGS.markSearched}
      </button>
      <button type="button" style={BTN} onClick={() => setArmed(false)}>
        {STRINGS.cancel}
      </button>
    </span>
  );
}

const CSS = `
.rs-plist{position:fixed;left:0;right:0;bottom:0;background:${COLORS.background};color:${COLORS.text};border-top:2px solid #888;max-height:calc(3*64px + 56px);overflow:hidden}
.rs-plist.open{max-height:80vh;overflow-y:auto}
.rs-plist ol{list-style:none;margin:0;padding:0}
.rs-plist li{display:flex;align-items:center;gap:8px;min-height:64px;border-bottom:1px solid #444;padding:0 8px}
.rs-disc{width:40px;height:40px;border-radius:50%;background:${COLORS.furniture};color:${COLORS.text};border:1px solid #fff;display:flex;align-items:center;justify-content:center;font-weight:700;flex:none}
.rs-disc.halo{box-shadow:0 0 0 4px ${COLORS.background},0 0 0 8px #e00}
@media (orientation:landscape),(min-width:900px){
.rs-plist{left:auto;top:0;width:360px;max-height:none;overflow-y:auto;border-top:none;border-left:2px solid #888}
.rs-plist .rs-toggle{display:none}}
`;

interface Props {
  scene: SceneModel;
  onSelect: (roomId: string) => void;
  onMarkSearched: (roomId: string) => void;
  initiallyOpen?: boolean;
}

export function PriorityList({ scene, onSelect, onMarkSearched, initiallyOpen = false }: Props) {
  const [open, setOpen] = useState(initiallyOpen);
  const byId = new Map(scene.rooms.map((r) => [r.roomId, r] as const));
  return (
    <section class={open ? "rs-plist open" : "rs-plist"} aria-label={STRINGS.priorityList}>
      <style>{CSS}</style>
      <button type="button" class="rs-toggle" style={{ ...BTN, width: "100%" }} aria-expanded={open} onClick={() => setOpen(!open)}>
        {STRINGS.priorityList} ({scene.priority.length}) {open ? "▼" : "▲"}
      </button>
      <ol>
        {scene.priority.map((id) => {
          const r = byId.get(id);
          if (r === undefined) return null;
          return (
            <li key={id} style={{ opacity: r.searched ? 0.35 : 1 }}>
              <button
                type="button"
                aria-label={r.ariaLabel}
                onClick={() => onSelect(id)}
                style={{ ...BTN, flex: 1, display: "flex", alignItems: "center", gap: 8, textAlign: "left", background: "none", border: "none", color: COLORS.text }}
              >
                <span class={r.halo ? "rs-disc halo" : "rs-disc"}>{r.rank}</span>
                <span>
                  <strong>{r.name}</strong> {r.label} {r.confidenceText}
                  {r.subText[0] !== undefined && <div style={{ fontSize: "0.85em" }}>{r.subText[0]}</div>}
                </span>
              </button>
              <MarkSearched room={r} onMarkSearched={onMarkSearched} />
            </li>
          );
        })}
      </ol>
    </section>
  );
}
