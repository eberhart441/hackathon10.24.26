import type { RoomDescriptor } from '../scene/model';
import { CrewIcon, StateIcon } from './icons';

interface Props {
  room: RoomDescriptor;
  onTap: (roomId: string) => void;
  compact?: boolean;
}

// Pinned over the room centroid by both renderers. Real DOM text: crisp, tappable, readable by
// screen readers (Kiro R16.3, R19.2).
export function RoomLabel({ room, onTap, compact }: Props) {
  const o = room.occupancy;
  const cls = ['room-label', o ? `st-${o.state}` : 'st-idle', o?.searched ? 'searched' : '', room.greyed ? 'greyed' : '', compact ? 'compact' : '']
    .filter(Boolean)
    .join(' ');
  return (
    <button type="button" class={cls} aria-label={room.ariaLabel} onClick={() => onTap(room.id)}>
      <div class="rl-top">
        {o?.rank ? <span class={`rank${o.isTop ? ' top' : ''}`}>{o.rank}</span> : null}
        <span class="rl-name">{room.name}</span>
        {room.simulated && !compact ? <span class="chip chip-sim">SIMULATED</span> : null}
      </div>
      {o ? (
        <>
          <div class="rl-state">
            <StateIcon state={o.state} />
            <span class="rl-label">{o.label}</span>
            {!compact ? <span class="rl-conf">{o.confText}</span> : null}
          </div>
          {!compact && o.detailText ? <div class="rl-detail">{o.detailText}</div> : null}
          {!compact && o.subLabel ? <div class="rl-detail">{o.subLabel}</div> : null}
          {!compact && o.annotation ? <div class="rl-note">{o.annotation}</div> : null}
          <div class="rl-chips">
            {room.simulated && compact ? <span class="chip chip-sim">SIMULATED</span> : null}
            {o.searched ? <span class="chip chip-searched">✓ SEARCHED</span> : null}
            {o.uncalibrated ? <span class="chip chip-warn">⚠ Uncalibrated</span> : null}
          </div>
        </>
      ) : null}
      {room.crew.length ? (
        <div class="rl-crew">
          {room.crew.map((c) => (
            <span class="crew" key={c.tagId}>
              <CrewIcon hollow={c.hollow} size={16} />
              <span>{c.hollow ? c.text : c.tagId}</span>
            </span>
          ))}
        </div>
      ) : null}
    </button>
  );
}
