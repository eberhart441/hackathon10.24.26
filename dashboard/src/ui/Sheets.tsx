import type { ComponentChildren } from 'preact';
import type { HealthMessage } from '../types';
import type { RoomDescriptor } from '../scene/model';
import { ageText } from '../scene/format';
import { CrewIcon, StateIcon } from './icons';
import { SearchedButton } from './PriorityList';

export function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: ComponentChildren }) {
  return (
    <div class="sheet-backdrop" onClick={onClose}>
      <div class="sheet" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div class="sheet-head">
          <h2>{title}</h2>
          <button type="button" class="btn-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

// Room details at most 2 taps away (parent R13.6).
export function RoomSheet({ room, onClose, onSearched }: { room: RoomDescriptor; onClose: () => void; onSearched: (id: string) => Promise<void> }) {
  const o = room.occupancy;
  return (
    <Sheet title={room.name} onClose={onClose}>
      {room.simulated ? <p class="chip chip-sim">SIMULATED ROOM</p> : null}
      {o ? (
        <>
          <div class={`sheet-state st-${o.state}`}>
            <StateIcon state={o.state} size={28} />
            <span>{o.label}</span>
            {o.rank ? <span class={`rank${o.isTop ? ' top' : ''}`}>{o.rank}</span> : null}
          </div>
          <dl class="facts">
            <dt>Confidence</dt>
            <dd>{o.confText}</dd>
            <dt>Last activity</dt>
            <dd>{o.detailText ?? '—'}</dd>
            <dt>At alarm</dt>
            <dd>{o.alarmTimeLabel ?? '—'}</dd>
            <dt>Link health</dt>
            <dd>{o.linkHealth}</dd>
            {o.source ? (
              <>
                <dt>Source</dt>
                <dd>
                  <span class="chip">{o.source}</span>
                </dd>
              </>
            ) : null}
          </dl>
          {o.subLabel ? <p class="note">{o.subLabel}</p> : null}
          {o.annotation ? <p class="note">{o.annotation}</p> : null}
          {o.uncalibrated ? <p class="note warn">⚠ Uncalibrated room: readings are not trustworthy.</p> : null}
          {room.crew.length ? (
            <ul class="crew-list">
              {room.crew.map((c) => (
                <li key={c.tagId}>
                  <CrewIcon hollow={c.hollow} size={20} /> {c.text}
                </li>
              ))}
            </ul>
          ) : null}
          <SearchedButton roomId={room.id} name={room.name} searched={o.searched} onSearched={onSearched} />
        </>
      ) : (
        <p class="note">No incident is open. Room states are only shown during an incident.</p>
      )}
    </Sheet>
  );
}

// Health chip detail: each fault with cause and suggested action (parent R19.4).
export function HealthSheet({ health, onClose }: { health: HealthMessage | null; onClose: () => void }) {
  const faults = health?.nodes.filter((n) => n.status !== 'ok') ?? [];
  return (
    <Sheet title="Sensor health" onClose={onClose}>
      <p class="note">{health?.summary ?? 'No health data from the hub yet.'}</p>
      <ul class="fault-list">
        {faults.map((n) => (
          <li key={n.node_id} class={`fault-item st-${n.status}`}>
            <strong>
              {n.node_id} ({n.role}) · {n.status.replace('_', ' ')}
            </strong>
            {n.cause ? <span>Cause: {n.cause}</span> : null}
            {n.action ? <span>Do: {n.action}</span> : null}
          </li>
        ))}
        {health?.tag_faults.map((t) => (
          <li key={t.tag_id} class="fault-item">
            <strong>{t.tag_id} tag not heard</strong>
            <span>
              Last heard {t.last_room ?? 'unknown room'}, {ageText(t.silent_s)} ago
            </span>
            <span>Do: check on the responder and the tag battery.</span>
          </li>
        ))}
      </ul>
      {health ? (
        <ul class="node-list">
          {health.nodes.map((n) => (
            <li key={n.node_id}>
              <span class={`led st-${n.status}`} aria-hidden="true" />
              {n.node_id} · {n.room_id} · {n.status.replace('_', ' ')}
              {n.measured_pps !== undefined ? ` · ${n.measured_pps} pps` : ''}
            </li>
          ))}
        </ul>
      ) : null}
    </Sheet>
  );
}
