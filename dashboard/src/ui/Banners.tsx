// Full-width hub-lost / reconnecting / all-searched banners (Req 10.4, 12.2).
import type { SceneModel } from "../scene/model";
import { STRINGS } from "../scene/strings";
import { COLORS } from "../scene/palette";

const bar = { width: "100%", minHeight: "56px", boxSizing: "border-box" as const, padding: "12px", fontWeight: 700, fontSize: "18px", color: COLORS.text };

export function Banners({ banners }: { banners: SceneModel["banners"] }) {
  return (
    <>
      {banners.hubLost && (
        <div role="alert" style={{ ...bar, background: COLORS.alarmRed }}>
          {STRINGS.hubLost}
          {banners.reconnecting && <div style={{ fontWeight: 400 }}>{STRINGS.reconnecting}</div>}
        </div>
      )}
      {!banners.hubLost && banners.reconnecting && (
        <div role="status" style={{ ...bar, background: COLORS.furniture }}>{STRINGS.reconnecting}</div>
      )}
      {banners.allSearched && (
        <div role="status" style={{ ...bar, background: COLORS.background, border: `2px solid ${COLORS.text}` }}>{STRINGS.allSearched}</div>
      )}
    </>
  );
}
