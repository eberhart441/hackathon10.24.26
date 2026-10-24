import { useLayoutEffect, useRef, useState } from 'preact/hooks';
import type { Floorplan, RoomStateCode, Vec2 } from '../types';
import type { RoomDescriptor, SceneModel } from '../scene/model';
import { bounds, doorViews, floorBounds, inradiusAt, wallSegments, wallsPath } from '../scene/geometry';
import { STATE_FILL, STATE_PATTERN } from '../scene/palette';
import { RoomLabel } from '../ui/RoomLabel';
import { CrewIcon, StateIcon } from '../ui/icons';

interface Props {
  plan: Floorplan;
  model: SceneModel;
  floorId: string;
  onRoomTap: (roomId: string) => void;
  snapshot?: boolean; // draw alarm_time_state instead of the live state
  minimal?: boolean; // phone view: only the rooms, each with its state inside it, and responder markers
}

const PAD = 0.6;
const IDLE_FLOOR = '#1C222B';

const pts = (poly: Vec2[]) => poly.map(([x, y]) => `${x},${y}`).join(' ');

// Top-down SVG plan: the safety net renderer, the snapshot inset, and the 3D fallback (Kiro R16.1).
export function Plan2D({ plan, model, floorId, onRoomTap, snapshot, minimal }: Props) {
  const floor = plan.floors.find((f) => f.id === floorId) ?? plan.floors[0];
  const rooms = model.rooms.filter((r) => r.floorId === floor.id);
  const pad = minimal ? 0.15 : PAD;
  const b = floorBounds(floor);
  const vb = { x: b.minX - pad, y: b.minY - pad, w: b.maxX - b.minX + 2 * pad, h: b.maxY - b.minY + 2 * pad };
  // A walls-only DXF gives the real walls; otherwise they are drawn along the room outlines.
  const walls = floor.walls?.length ? [] : wallSegments(floor.rooms);
  // The phone shows rooms only: no boards or radio links.
  const nodes = minimal ? [] : plan.nodes.filter((n) => floor.rooms.some((r) => r.id === n.room));
  const links = plan.links.filter((l) => nodes.some((n) => n.id === l.tx) && nodes.some((n) => n.id === l.rx));
  const nodeById = new Map(nodes.map((n) => [n.id, n]));

  const wrap = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 1, h: 1 });
  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth || 1, h: el.clientHeight || 1 }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Match preserveAspectRatio="xMidYMid meet" so HTML labels land on the right spot.
  const scale = Math.min(box.w / vb.w, box.h / vb.h);
  const offX = (box.w - vb.w * scale) / 2;
  const offY = (box.h - vb.h * scale) / 2;
  const toPx = ([x, y]: Vec2) => [offX + (x - vb.x) * scale, offY + (vb.y + vb.h - y) * scale];

  const shownState = (r: RoomDescriptor): RoomStateCode | null =>
    snapshot ? r.occupancy?.alarmTimeState ?? null : r.occupancy?.state ?? null;

  return (
    <div class={`plan2d${snapshot ? ' is-snapshot' : ''}`} ref={wrap}>
      <svg viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label={`${floor.name} plan`}>
        <PatternDefs />
        <g transform={`translate(0 ${2 * vb.y + vb.h}) scale(1 -1)`}>
          <rect class="grid-bg" x={vb.x} y={vb.y} width={vb.w} height={vb.h} fill="url(#grid)" />
          {rooms.map((r) => {
            const st = shownState(r);
            const fill = snapshot ? (st ? STATE_FILL[st] : IDLE_FLOOR) : r.occupancy?.fill ?? IDLE_FLOOR;
            const pattern = st ? STATE_PATTERN[st] : null;
            const o = r.occupancy;
            const ringR = Math.max(0.3, inradiusAt(r.centroid, r.def.polygon) - 0.1);
            return (
              <g
                key={r.id}
                class={`room${o?.searched && !snapshot ? ' searched' : ''}`}
                onClick={() => onRoomTap(r.id)}
                role="button"
                aria-label={r.ariaLabel}
              >
                <clipPath id={`clip-${r.id}${snapshot ? '-s' : ''}`}>
                  <polygon points={pts(r.def.polygon)} />
                </clipPath>
                <polygon points={pts(r.def.polygon)} fill={fill} />
                {pattern && pattern !== 'solid' ? <polygon points={pts(r.def.polygon)} fill={`url(#pat-${pattern})`} /> : null}
                {/* The phone has no header badge, so simulated data is marked inside every room. */}
                {r.simulated || (minimal && model.simulated) ? <polygon points={pts(r.def.polygon)} fill="url(#pat-sim)" /> : null}
                {!snapshot && st === 'MOTION' && !r.greyed ? (
                  <g clip-path={`url(#clip-${r.id})`}>
                    {[0, 1, 2].map((i) => (
                      <circle
                        class="ring"
                        style={{ animationDelay: `${i * 0.4}s`, transformOrigin: `${r.centroid[0]}px ${r.centroid[1]}px` }}
                        cx={r.centroid[0]}
                        cy={r.centroid[1]}
                        r={ringR}
                        key={i}
                      />
                    ))}
                  </g>
                ) : null}
                {!snapshot && st === 'POSSIBLE' && !r.greyed ? <polygon class="glow" points={pts(r.def.polygon)} /> : null}
                {!snapshot &&
                  r.def.furniture.map((f, i) => <rect key={i} class="furniture" x={f.x} y={f.y} width={f.w} height={f.d} rx="0.05" />)}
              </g>
            );
          })}

          {floor.walls?.length ? <path class="wall-mass" d={wallsPath(floor.walls)} fill-rule="evenodd" /> : null}
          {walls.map((w, i) => (
            <line key={i} class="wall" x1={w.a[0]} y1={w.a[1]} x2={w.b[0]} y2={w.b[1]} />
          ))}
          {floor.rooms.flatMap((r) =>
            doorViews(r).map((d, i) => {
              const tip: Vec2 = [d.hinge[0] + d.inward[0] * d.width, d.hinge[1] + d.inward[1] * d.width];
              // Sweep direction depends on which side the leaf opens to.
              const cross = (d.latch[0] - d.hinge[0]) * d.inward[1] - (d.latch[1] - d.hinge[1]) * d.inward[0];
              return (
                <g key={`${r.id}-d${i}`} class="door">
                  <line x1={d.hinge[0]} y1={d.hinge[1]} x2={tip[0]} y2={tip[1]} />
                  <path d={`M ${d.latch[0]} ${d.latch[1]} A ${d.width} ${d.width} 0 0 ${cross > 0 ? 1 : 0} ${tip[0]} ${tip[1]}`} />
                </g>
              );
            }),
          )}

          {!snapshot &&
            links.map((l) => {
              const tx = nodeById.get(l.tx)!;
              const rx = nodeById.get(l.rx)!;
              const txSt = model.nodes[tx.id]?.status;
              const rxSt = model.nodes[rx.id]?.status;
              if (rxSt === 'offline') return null; // hidden; "!" shown on the RX (Kiro R16.6)
              const cls = txSt === 'tx_dead' ? 'link dead' : rxSt === 'degraded' ? 'link degraded' : 'link';
              return <line key={`${l.tx}-${l.rx}`} class={cls} x1={tx.pos[0]} y1={tx.pos[1]} x2={rx.pos[0]} y2={rx.pos[1]} />;
            })}
          {!snapshot &&
            nodes.map((n) => {
              const st = model.nodes[n.id]?.status ?? 'unknown';
              const fault = st === 'offline' || st === 'tx_dead';
              return (
                <g key={n.id} class={`node st-${st}`} transform={`translate(${n.pos[0]} ${n.pos[1]})`}>
                  <rect x="-0.11" y="-0.11" width="0.22" height="0.22" rx="0.04" />
                  {fault ? (
                    <g class="bang">
                      <line x1="0" y1="0.42" x2="0" y2="0.22" />
                      <circle cx="0" cy="0.15" r="0.025" />
                    </g>
                  ) : null}
                </g>
              );
            })}
        </g>
      </svg>
      <div class="plan2d-labels">
        {rooms.map((r) => {
          const [x, y] = toPx(r.centroid);
          return (
            <div class="label-pin" style={{ left: `${x}px`, top: `${y}px` }} key={r.id}>
              {snapshot ? (
                <span class={`snap-label st-${shownState(r) ?? 'idle'}`}>{r.occupancy?.alarmTimeLabel ?? '—'}</span>
              ) : minimal ? (
                <PhoneLabel room={r} hubLost={model.hubLost} maxWidth={roomWidthPx(r, scale)} />
              ) : (
                <RoomLabel room={r} onTap={onRoomTap} compact={box.w < 420} />
              )}
            </div>
          );
        })}
        {/* A responder located in one room is a badge in that room's label (see PhoneLabel); one
            that is only near two rooms gets a chip between them, never a single room. */}
        {minimal
          ? model.crewChips
              .filter((c) => c.floorId === floor.id && c.rooms.length)
              .map((c) => {
                const cs = c.rooms.map((id) => rooms.find((r) => r.id === id)?.centroid).filter(Boolean) as Vec2[];
                if (!cs.length) return null;
                const [x, y] = toPx([cs.reduce((s, p) => s + p[0], 0) / cs.length, cs.reduce((s, p) => s + p[1], 0) / cs.length]);
                return (
                  <div class="label-pin chip-pin" style={{ left: `${x}px`, top: `${y + 34}px` }} key={c.tagId}>
                    <span class={`crew-chip${c.you ? ' you' : ''}`}>{c.you ? c.text.replace(c.tagId, 'YOU') : c.text}</span>
                  </div>
                );
              })
          : null}
      </div>
    </div>
  );
}

// Widest a label may be and still sit inside its room on screen.
function roomWidthPx(r: RoomDescriptor, scale: number): number {
  const b = bounds([r.def.polygon]);
  return Math.max(64, (b.maxX - b.minX) * scale - 8);
}

// Phone view: everything about a room is inside the room (name, priority, state, one status line).
function PhoneLabel({ room, hubLost, maxWidth }: { room: RoomDescriptor; hubLost: boolean; maxWidth: number }) {
  const o = room.occupancy;
  if (!o) {
    return (
      <span class="mini-label st-idle" style={{ maxWidth: `${maxWidth}px` }}>
        <span class="ml-name">{room.name}</span>
        <span class="ml-detail">{hubLost ? 'No hub connection' : 'No alarm'}</span>
      </span>
    );
  }
  const detail = o.searched ? 'Searched' : o.detailText ?? o.annotation ?? o.subLabel;
  return (
    <span class={`mini-label st-${o.state}${o.searched ? ' searched' : ''}${room.greyed ? ' greyed' : ''}`} style={{ maxWidth: `${maxWidth}px` }}>
      <span class="ml-name">
        {o.rank ? <span class={`rank${o.isTop ? ' top' : ''}`}>{o.rank}</span> : null}
        {room.name}
      </span>
      <span class="ml-state">
        <StateIcon state={o.state} size={14} />
        {o.label}
      </span>
      {detail ? <span class="ml-detail">{detail}</span> : null}
      <CrewBadges room={room} />
    </span>
  );
}

// Responders located in this room: the phone's own tag as YOU, the others by tag id. A room, never
// a measured point; hollow (dashed) when the tag was last heard here but has gone quiet.
function CrewBadges({ room }: { room: RoomDescriptor }) {
  if (!room.crew.length) return null;
  const crew = [...room.crew].sort((a, b) => Number(b.you) - Number(a.you));
  return (
    <span class="ml-crew">
      {crew.map((c) => (
        <span
          key={c.tagId}
          class={`crew-badge${c.hollow ? ' hollow' : ''}${c.you ? ' you' : ''}`}
          role="img"
          aria-label={c.you ? `You are here${c.hollow ? ' (last heard)' : ''}` : `Responder ${c.tagId}${c.hollow ? ', last heard here' : ''}`}
        >
          <CrewIcon hollow={c.hollow} size={c.you ? 16 : 13} />
          {c.you ? 'YOU' : c.tagId}
        </span>
      ))}
    </span>
  );
}

function PatternDefs() {
  // Pattern tiles in metres so density matches across rooms. Ink is translucent black so the
  // fill colour shows through; patterns survive grayscale (Kiro R9.2).
  return (
    <defs>
      <pattern id="grid" width="1" height="1" patternUnits="userSpaceOnUse">
        <path d="M1 0H0V1" fill="none" stroke="#1A2029" stroke-width="0.02" />
      </pattern>
      <pattern id="pat-hatch" width="0.22" height="0.22" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="0.08" height="0.22" fill="rgba(0,0,0,0.38)" />
      </pattern>
      <pattern id="pat-crosshatch" width="0.2" height="0.2" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="0.05" height="0.2" fill="rgba(0,0,0,0.42)" />
        <rect width="0.2" height="0.05" fill="rgba(0,0,0,0.42)" />
      </pattern>
      <pattern id="pat-dots" width="0.3" height="0.3" patternUnits="userSpaceOnUse">
        <circle cx="0.15" cy="0.15" r="0.04" fill="rgba(255,255,255,0.28)" />
      </pattern>
      <pattern id="pat-sim" width="2.4" height="1.2" patternUnits="userSpaceOnUse" patternTransform="rotate(-25) scale(1 -1)">
        <text x="0.1" y="0.7" font-size="0.32" font-weight="700" fill="rgba(255,255,255,0.13)" font-family="Atkinson Hyperlegible, system-ui, sans-serif">
          SIMULATED
        </text>
      </pattern>
    </defs>
  );
}
