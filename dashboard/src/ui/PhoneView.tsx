import type { CrewTag, Floorplan, RoomStateCode } from '../types';
import type { RoomDescriptor, SceneModel } from '../scene/model';
import type { RoomHistory, StoreState } from '../store';
import { HISTORY_S } from '../store';
import { ageText } from '../scene/format';
import { bounds } from '../scene/geometry';
import { STATE_FILL, STATE_LABEL } from '../scene/palette';
import { Plan2D } from '../render2d/Plan2D';
import { DISCLAIMER } from './Header';
import { CrewIcon, StateIcon } from './icons';

interface Props {
  plan: Floorplan;
  model: SceneModel;
  store: StoreState;
  now: number;
  floorId: string;
  onFloor: (floorId: string) => void;
}

// The responder's phone: a 2D plan, where the responder tags are, and each room's movement in
// priority order. Nothing to tap but floors. The laptop keeps the full presenter view.
export function PhoneView({ plan, model, store, now, floorId, onFloor }: Props) {
  const rooms = model.ordered.filter((r) => r.floorId === floorId);
  const faults = store.health ? store.health.nodes.filter((n) => n.status !== 'ok').length + store.health.tag_faults.length : 0;
  return (
    <div class={`app phone${model.alarm ? ' alarm' : ''}`}>
      <header class="p-hdr">
        <div class="p-status">
          <span class={`dot${store.recording?.indicator.startsWith('Recording') ? ' on' : ''}`} aria-hidden="true" />
          <span>{store.recording?.indicator ?? 'Waiting for hub…'}</span>
          {faults ? <span class="p-faults">⚠ {store.health?.summary}</span> : null}
        </div>
        <p class="disclaimer">{DISCLAIMER}</p>
        {model.simulated ? <span class="badge sim">SIMULATED DATA</span> : null}
      </header>
      {model.hubLost ? (
        <div class="banner hub-lost" role="alert">
          HUB LOST — no update for {model.hubLostAgeText ?? 'a while'}. Showing last known states only.
        </div>
      ) : store.reconnecting ? (
        <div class="banner info" role="status">Reconnecting…</div>
      ) : null}

      {model.occupancyShown ? <Responders tags={store.crew?.tags ?? []} model={model} /> : null}

      {plan.floors.length > 1 ? (
        <nav class="floor-tabs" aria-label="Floors">
          {model.floors.map((f) => (
            <button
              type="button"
              key={f.id}
              class={`tab${f.id === floorId ? ' on' : ''}`}
              aria-pressed={f.id === floorId}
              onClick={() => onFloor(f.id)}
              aria-label={`${f.name}${model.occupancyShown ? `, ${f.attention} rooms to search, ${f.crew} crew` : ''}`}
            >
              <span>{f.name}</span>
              {model.occupancyShown && f.attention ? <span class="count attn">{f.attention}</span> : null}
              {model.occupancyShown && f.crew ? (
                <span class="count crew">
                  <CrewIcon hollow={false} size={14} /> {f.crew}
                </span>
              ) : null}
            </button>
          ))}
        </nav>
      ) : null}

      <section class="p-plan" aria-label="Floor plan" style={{ aspectRatio: floorAspect(plan, floorId) }}>
        <Plan2D plan={plan} model={model} floorId={floorId} onRoomTap={() => undefined} minimal />
      </section>

      {model.occupancyShown ? (
        <ol class="p-rooms" aria-label="Rooms in search priority order">
          {rooms.map((r) => (
            <RoomRow key={r.id} room={r} history={store.history[r.id] ?? []} nowS={now / 1000} />
          ))}
        </ol>
      ) : (
        <p class="p-idle">Normal mode. Room movement appears here once an alarm is triggered.</p>
      )}
    </div>
  );
}

// Width / height of the floor drawing (with the plan's 0.6 m margin), so the box hugs the plan.
function floorAspect(plan: Floorplan, floorId: string): string {
  const floor = plan.floors.find((f) => f.id === floorId) ?? plan.floors[0];
  const b = bounds(floor.rooms.map((r) => r.polygon));
  const w = b.maxX - b.minX + 1.2;
  const h = b.maxY - b.minY + 1.2;
  return `${w} / ${Math.max(h, w / 3)}`; // never flatter than 3:1, so labels still fit
}

function Responders({ tags, model }: { tags: CrewTag[]; model: SceneModel }) {
  const name = (id: string | null) => model.rooms.find((r) => r.id === id)?.name ?? id ?? 'unknown room';
  if (!tags.length) return <p class="p-crew none">No responder tag heard yet</p>;
  return (
    <ul class="p-crew" aria-label="Responders">
      {tags.map((t) => {
        let where: string;
        if (t.marker === 'hollow' || t.location_kind === 'lost') where = `not heard for ${ageText(t.last_heard_s)} · last in ${name(t.room_id)}`;
        else if (t.location_kind === 'room' && t.confidence_band !== 'low') where = `in ${name(t.room_id)} · heard ${ageText(t.last_heard_s)} ago`;
        else if (t.location_kind === 'between' || t.near_rooms.length < 2) where = 'between rooms';
        else where = `near ${name(t.near_rooms[0])} / ${name(t.near_rooms[1])}`;
        return (
          <li key={t.tag_id} class={t.marker === 'hollow' ? 'lost' : ''}>
            <CrewIcon hollow={t.marker === 'hollow'} size={22} />
            <strong>{t.tag_id}</strong> {where}
          </li>
        );
      })}
    </ul>
  );
}

function RoomRow({ room, history, nowS }: { room: RoomDescriptor; history: RoomHistory; nowS: number }) {
  const o = room.occupancy!;
  const since = sinceStateChange(history, o.state);
  return (
    <li class={`p-room st-${o.state}${o.searched ? ' searched' : ''}${room.greyed ? ' greyed' : ''}`} aria-label={room.ariaLabel}>
      <div class="p-room-top">
        {o.rank ? <span class={`rank${o.isTop ? ' top' : ''}`}>{o.rank}</span> : <span class="rank none" aria-hidden="true" />}
        <span class="p-room-name">{room.name}</span>
        {room.simulated ? <span class="chip chip-sim">SIM</span> : null}
        {room.crew.some((c) => !c.hollow) ? (
          <span class="chip chip-crew" title="Responder here">
            <CrewIcon hollow={false} size={13} /> {room.crew.filter((c) => !c.hollow).map((c) => c.tagId).join(', ')}
          </span>
        ) : null}
      </div>
      <div class="p-room-state">
        <StateIcon state={o.state} size={18} />
        <strong>{o.label}</strong>
        <span class="p-conf">{o.confText}</span>
        {since !== null ? <span class="p-since">for {ageText(nowS - since)}</span> : null}
      </div>
      {o.detailText ? <div class="p-detail">{o.detailText}</div> : null}
      {o.subLabel ? <div class="p-detail">{o.subLabel}</div> : null}
      {o.annotation ? <div class="p-detail note">{o.annotation}</div> : null}
      <HistoryStrip history={history} nowS={nowS} />
    </li>
  );
}

// When the room entered its current state, from the in-memory history (null if unknown).
function sinceStateChange(history: RoomHistory, state: RoomStateCode): number | null {
  if (!history.length || history[history.length - 1][1] !== state) return null;
  let i = history.length - 1;
  while (i > 0 && history[i - 1][1] === state) i--;
  return history[i][0];
}

// The last HISTORY_S seconds as coloured segments, oldest left. Each segment is also labelled for
// screen readers; colour is never the only signal (the row's state label is right above).
function HistoryStrip({ history, nowS }: { history: RoomHistory; nowS: number }) {
  if (history.length < 2) return null;
  const start = nowS - HISTORY_S;
  const segs: { from: number; to: number; state: RoomStateCode }[] = [];
  history.forEach(([t, s], i) => {
    const to = i + 1 < history.length ? history[i + 1][0] : nowS;
    const from = Math.max(t, start);
    if (to <= from) return;
    const last = segs[segs.length - 1];
    if (last && last.state === s) last.to = to;
    else segs.push({ from, to, state: s });
  });
  const motionS = segs.filter((s) => s.state === 'MOTION').reduce((a, s) => a + (s.to - s.from), 0);
  return (
    <div class="p-hist">
      <div class="p-hist-bar" role="img" aria-label={`Last ${HISTORY_S / 60} minutes: motion for ${ageText(motionS)}`}>
        {segs.map((s, i) => (
          <span
            key={i}
            class={`seg st-${s.state}`}
            style={{ left: `${((s.from - start) / HISTORY_S) * 100}%`, width: `${((s.to - s.from) / HISTORY_S) * 100}%`, background: STATE_FILL[s.state] }}
            title={`${STATE_LABEL[s.state]} ${ageText(s.to - s.from)}`}
          />
        ))}
      </div>
      <div class="p-hist-legend">
        <span>−{HISTORY_S / 60} min</span>
        <span>motion {ageText(motionS)} of the last {HISTORY_S / 60} min</span>
        <span>now</span>
      </div>
    </div>
  );
}
