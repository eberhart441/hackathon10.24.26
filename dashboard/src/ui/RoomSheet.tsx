// Room detail sheet (Req 11.8, 19.1, 19.2).
import type { RoomDescriptor } from "../scene/model";
import { STRINGS } from "../scene/strings";
import type { RoomEntry } from "../ws/messages";
import { labelFor } from "../ws/messages";
import { MarkSearched } from "./PriorityList";

const LINK = { ok: STRINGS.linkOk, degraded: STRINGS.linkDegraded, offline: STRINGS.linkOffline } as const;

interface Props {
  room: RoomDescriptor;
  entry: RoomEntry | undefined;
  onClose: () => void;
  onMarkSearched: (roomId: string) => void;
}

export function RoomSheet({ room, entry, onClose, onMarkSearched }: Props) {
  return (
    <section
      role="dialog"
      aria-label={room.ariaLabel}
      style={{ position: "fixed", left: 0, right: 0, bottom: 0, background: "#fff", border: "2px solid #000", padding: 12, zIndex: 10 }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0 }}>{room.name}</h2>
        <button type="button" style={{ minWidth: 56, minHeight: 56 }} aria-label={STRINGS.close} onClick={onClose}>
          ✕
        </button>
      </div>
      <dl style={{ margin: "8px 0" }}>
        <dt>{STRINGS.state}</dt>
        <dd>{room.label ?? STRINGS.none}</dd>
        <dt>{STRINGS.confidence}</dt>
        <dd>{room.confidenceText ?? STRINGS.none}</dd>
        <dt>{STRINGS.lastActivity}</dt>
        {room.subText.length === 0 ? <dd>{STRINGS.none}</dd> : room.subText.map((t) => <dd key={t}>{t}</dd>)}
        {room.chips.length > 0 && <dd>{room.chips.join(" · ")}</dd>}
        {entry !== undefined && (
          <>
            <dt>{STRINGS.atAlarm}</dt>
            <dd>{entry.alarm_time_state === null ? STRINGS.none : labelFor(entry.alarm_time_state)}</dd>
            <dt>{STRINGS.linkHealth}</dt>
            <dd>{LINK[entry.link_health]}</dd>
            <dd>
              <span style={{ border: "1px solid #000", padding: "0 4px" }}>
                {entry.source === "edge" ? STRINGS.sourceEdge : STRINGS.sourceHub}
              </span>{" "}
              {STRINGS.modelVersion} {entry.model_ver ?? STRINGS.none}
            </dd>
          </>
        )}
        <dt>{STRINGS.crewPresent}</dt>
        {room.crew.length === 0 ? <dd>{STRINGS.none}</dd> : room.crew.map((c) => <dd key={c.tagId}>{c.text}</dd>)}
      </dl>
      {room.label !== null && <MarkSearched room={room} onMarkSearched={onMarkSearched} />}
    </section>
  );
}
