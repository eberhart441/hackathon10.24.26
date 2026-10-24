// Renderer_2D: top-down SVG floor plan drawn from the Scene_Model (meters, y flipped).
import type { FloorPlan, RoomPlan } from "../floorplan/types";
import type { RoomDescriptor, SceneModel } from "../scene/model";
import { COLORS, withSaturation } from "../scene/palette";
import { PATTERNS, SIMULATED_OVERLAY, svgPatternId, svgPatternMarkup, type PatternId } from "../scene/patterns";
import type { HealthMsg } from "../ws/messages";
import "./svg.css";

type P = [number, number];
const WALL = 0.12;
const PAD = 0.6;
const GREY = "#4A4F58";
const HEALTH_COLOR = { ok: "#2EBD59", degraded: "#FFB020", offline: "#111111", tx_dead: "#111111" } as const;

const pts = (poly: P[]) => poly.map(([x, y]) => `${x},${-y}`).join(" ");

/** Wall segments with door gaps, plus door swing arcs. */
function walls(room: RoomPlan, c: P) {
  const segs: [P, P][] = [];
  const arcs: string[] = [];
  const poly = room.polygon;
  poly.forEach((a, i) => {
    const b = poly[(i + 1) % poly.length]!;
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (len === 0) return;
    const ux = (b[0] - a[0]) / len, uy = (b[1] - a[1]) / len;
    const at = (t: number): P => [a[0] + ux * t, a[1] + uy * t];
    const doors = room.doors.filter((d) => d.wall === i).sort((d, e) => d.offset - e.offset);
    let t = 0;
    for (const d of doors) {
      segs.push([at(t), at(d.offset)]);
      t = d.offset + d.width;
      // Quarter circle hinged at the door start, swinging toward (in) or away from (out) the centroid.
      const h = at(d.offset), e = at(t);
      let nx = -uy, ny = ux;
      const toC = (c[0] - h[0]) * nx + (c[1] - h[1]) * ny;
      if ((toC < 0) === (d.swing === "in")) { nx = -nx; ny = -ny; }
      const o: P = [h[0] + nx * d.width, h[1] + ny * d.width];
      const cross = ux * ny - uy * nx; // orientation in world coords; y flip inverts sweep
      const sweep = cross > 0 ? 0 : 1;
      arcs.push(`M${h[0]},${-h[1]} L${o[0]},${-o[1]} A${d.width},${d.width} 0 0 ${sweep} ${e[0]},${-e[1]}`);
    }
    segs.push([at(t), b]);
  });
  return { segs, arcs };
}

function Label({ d }: { d: RoomDescriptor }) {
  if (!d.centroid) return null;
  const [x, y] = d.centroid;
  const lines = [d.name, [d.label, d.confidenceText].filter(Boolean).join(" "), d.subText[0], d.chips.join(" · ")].filter(
    (s): s is string => !!s,
  );
  return (
    <g pointer-events="none">
      {d.rank !== null && (
        <g transform={`translate(${x},${-y - 0.25 - lines.length * 0.16})`}>
          {d.halo && <circle r={0.3} fill="none" stroke="#fff" stroke-width={0.08} />}
          <circle r={0.2} fill={COLORS.background} stroke="#fff" stroke-width={0.03} />
          <text text-anchor="middle" dy="0.09" font-size="0.24" fill="#fff" font-weight="bold">{d.rank}</text>
        </g>
      )}
      <text x={x} y={-y - (lines.length - 1) * 0.14} text-anchor="middle" font-size="0.22" fill={COLORS.text}
        stroke={COLORS.background} stroke-width={0.05} paint-order="stroke">
        {lines.map((l, i) => (
          <tspan key={i} x={x} dy={i === 0 ? 0 : 0.28} font-weight={i <= 1 ? "bold" : "normal"} font-size={i <= 1 ? 0.24 : 0.18}>{l}</tspan>
        ))}
      </text>
    </g>
  );
}

export function FloorSvg(props: {
  plan: FloorPlan;
  floorId: string;
  scene: SceneModel;
  health: HealthMsg | null;
  onSelectRoom: (id: string) => void;
}) {
  const { plan, floorId, scene, health, onSelectRoom } = props;
  const floor = plan.floors.find((f) => f.id === floorId);
  if (!floor) return null;
  const roomIds = new Set(floor.rooms.map((r) => r.id));
  const descs = new Map(scene.rooms.map((d) => [d.roomId, d] as const));
  const all = floor.rooms.flatMap((r) => r.polygon);
  const xs = all.map((p) => p[0]), ys = all.map((p) => p[1]);
  const minX = Math.min(...xs, 0), maxX = Math.max(...xs, 1), minY = Math.min(...ys, 0), maxY = Math.max(...ys, 1);
  const viewBox = `${minX - PAD} ${-maxY - PAD} ${maxX - minX + 2 * PAD} ${maxY - minY + 2 * PAD}`;

  const nodes = plan.nodes.filter((n) => roomIds.has(n.room));
  const nodeById = new Map(plan.nodes.map((n) => [n.id, n] as const));
  const status = (id: string) => health?.nodes.find((n) => n.node_id === id)?.status ?? null;
  const defs = (Object.keys(PATTERNS) as PatternId[]).map((id) => svgPatternMarkup(id)).join("");

  return (
    <svg viewBox={viewBox} width="100%" height="100%" style={{ background: COLORS.background, display: "block" }}>
      <defs dangerouslySetInnerHTML={{ __html: defs }} />
      {floor.rooms.map((room) => {
        const d = descs.get(room.id);
        const grey = !d || d.greyed || d.treatment === "NONE" || !d.fill;
        const fill = grey ? GREY : withSaturation(d.fill!, d.saturation);
        const p = pts(room.polygon);
        const select = () => onSelectRoom(room.id);
        return (
          <g key={room.id} class="rs-room" role="button" tabIndex={0} aria-label={d?.ariaLabel ?? room.name} onClick={select}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(); } }}
            opacity={d?.opacity ?? 1}>
            <polygon class="rs-floor" points={p} fill={fill} />
            {d?.pattern && d.pattern !== "solid" && <polygon points={p} fill={`url(#${svgPatternId(d.pattern)})`} />}
            {room.furniture.map((f, i) => (
              <rect key={i} x={f.rect[0]} y={-(f.rect[1] + f.rect[3])} width={f.rect[2]} height={f.rect[3]}
                fill={COLORS.furniture} opacity={0.6} />
            ))}
            {room.simulated && d?.centroid && (
              <text x={d.centroid[0]} y={-d.centroid[1] + 0.7} text-anchor="middle" font-size={SIMULATED_OVERLAY.fontSizeM * 2}
                fill={SIMULATED_OVERLAY.color} opacity={SIMULATED_OVERLAY.opacity} pointer-events="none"
                transform={`rotate(${-SIMULATED_OVERLAY.angleDeg} ${d.centroid[0]} ${-d.centroid[1] + 0.7})`}>
                {SIMULATED_OVERLAY.text}
              </text>
            )}
            {d?.treatment === "MOTION" && !d.greyed && d.centroid && (
              <circle class="rs-motion-ring" cx={d.centroid[0]} cy={-d.centroid[1]} r={0.6} />
            )}
          </g>
        );
      })}
      <g stroke={COLORS.wall} stroke-width={WALL} stroke-linecap="square" fill="none" pointer-events="none">
        {floor.rooms.map((room) => {
          const { segs, arcs } = walls(room, descs.get(room.id)?.centroid ?? room.polygon[0] ?? [0, 0]);
          return (
            <g key={room.id}>
              {segs.map(([a, b], i) => <line key={i} x1={a[0]} y1={-a[1]} x2={b[0]} y2={-b[1]} />)}
              {arcs.map((a, i) => <path key={`a${i}`} d={a} stroke-width={0.03} opacity={0.7} />)}
            </g>
          );
        })}
      </g>
      <g pointer-events="none">
        {plan.links.map((l, i) => {
          const tx = nodeById.get(l.tx), rx = nodeById.get(l.rx);
          if (!tx || !rx || !roomIds.has(tx.room)) return null;
          if (status(rx.id) === "offline") return null;
          const dead = status(tx.id) === "tx_dead";
          return (
            <line key={i} x1={tx.pos[0]} y1={-tx.pos[1]} x2={rx.pos[0]} y2={-rx.pos[1]}
              stroke={dead ? "#E53935" : "#9AA3B2"} stroke-width={0.03} stroke-dasharray={dead ? "0.08 0.16" : "0.2 0.1"} opacity={0.8} />
          );
        })}
        {nodes.map((n) => {
          const s = status(n.id);
          const [x, y] = n.pos;
          return (
            <g key={n.id}>
              <rect x={x - 0.09} y={-y - 0.09} width={0.18} height={0.18} fill="#C9CED6" stroke={COLORS.background} stroke-width={0.02} />
              {s && <circle cx={x + 0.12} cy={-y - 0.12} r={0.07} fill={HEALTH_COLOR[s]} stroke="#fff" stroke-width={0.015} />}
              {(s === "offline" || s === "tx_dead") && (
                <text x={x + 0.12} y={-y - 0.09} text-anchor="middle" font-size="0.1" fill="#fff" font-weight="bold">!</text>
              )}
            </g>
          );
        })}
      </g>
      {floor.rooms.map((room) => {
        const d = descs.get(room.id);
        return d ? <Label key={room.id} d={d} /> : null;
      })}
    </svg>
  );
}
