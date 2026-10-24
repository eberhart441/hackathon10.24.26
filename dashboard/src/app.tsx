// App shell: session → floor plan → WS → Store → Scene_Model → UI (Req 1.1, 1.4, 1.5, 11.7, 14.5).
import { useEffect, useState } from "preact/hooks";
import { createSession, type Session } from "./auth/session";
import type { FloorPlan, FloorplanError as FpError } from "./floorplan/types";
import { loadFloorplan } from "./floorplan/load";
import { FloorSvg } from "./render2d/svg";
import { buildSceneModel, type LinkStatus } from "./scene/model";
import { COLORS } from "./scene/palette";
import { STRINGS } from "./scene/strings";
import { dispatch, getState, subscribe } from "./store/store";
import { Banners } from "./ui/Banners";
import { FloorplanError } from "./ui/FloorplanError";
import { FloorTabs } from "./ui/FloorTabs";
import { Header } from "./ui/Header";
import { LaptopControls } from "./ui/LaptopControls";
import { PriorityList } from "./ui/PriorityList";
import { RoomSheet } from "./ui/RoomSheet";
import { createWsClient } from "./ws/client";

const session = createSession();

const ROOT = {
  minHeight: "100dvh", display: "flex", flexDirection: "column", background: COLORS.background, color: COLORS.text,
  padding: "env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)",
} as const;

/** Placeholder pair screen; task 8.3 replaces the body with the keypad. */
function PairScreen() {
  return (
    <main style={ROOT}>
      <p role="note">{STRINGS.disclaimer}</p>
      <h1>{STRINGS.pairTitle}</h1>
      <p>{STRINGS.pairPrompt}</p>
      {/* TODO(task 8.3): keypad + session.pairWithCode(code) */}
    </main>
  );
}

export function App() {
  const [sess, setSess] = useState<Session | null>(null);
  const [plan, setPlan] = useState<FloorPlan | null>(null);
  const [planErr, setPlanErr] = useState<FpError[] | string | null>(null);
  const [status, setStatus] = useState<LinkStatus>("connecting");
  const [, rerender] = useState(0);
  const [floorId, setFloorId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [triggered, setTriggered] = useState(false);

  useEffect(() => {
    void session.start().then(setSess);
  }, []);

  useEffect(() => {
    if (!sess || sess.kind === "needs_pair") return;
    let cancelled = false;
    void loadFloorplan(sess.token).then((r) => {
      if (cancelled) return;
      if (r.ok) {
        setPlan(r.plan);
        setFloorId(r.plan.floors[0]?.id ?? null);
      } else setPlanErr(r.kind === "invalid" ? r.errors : r.message);
    });
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = createWsClient(
      `${proto}://${location.host}/ws`,
      () => session.token(),
      (m, t) => dispatch(m, t),
      () => {
        session.clearToken();
        setSess({ kind: "needs_pair" });
      },
      { onDiscard: () => dispatch(null, Date.now()), onStatus: setStatus },
    );
    ws.start();
    const unsub = subscribe(() => rerender((n) => n + 1));
    const tick = setInterval(() => rerender((n) => n + 1), 1000);
    return () => {
      cancelled = true;
      ws.stop();
      unsub();
      clearInterval(tick);
    };
  }, [sess]);

  if (!sess) return <main style={ROOT}><p role="note">{STRINGS.disclaimer}</p></main>;
  if (sess.kind === "needs_pair") return <PairScreen />;
  if (planErr) return <FloorplanError errors={planErr} />;
  if (!plan || !floorId) return <main style={ROOT}><p role="note">{STRINGS.disclaimer}</p></main>;

  const state = getState();
  const scene = buildSceneModel(plan, state, Date.now(), status);
  const fire = scene.mode === "fire";
  const room = selected ? scene.rooms.find((r) => r.roomId === selected) : undefined;
  const entry = selected ? state.roomStates?.rooms.find((r) => r.room_id === selected) : undefined;
  const markSearched = (id: string) => void session.api.markSearched(id);

  return (
    <div style={ROOT}>
      <Header header={scene.header} health={state.health} simulatedTrigger={triggered && fire} />
      <Banners banners={scene.banners} />
      {sess.kind === "laptop" && (
        <LaptopControls api={session.api} fireMode={fire} onTriggered={() => setTriggered(true)} />
      )}
      {!fire && <p style={{ padding: "0 12px" }}>{STRINGS.idleTitle}</p>}
      <FloorTabs tabs={scene.floorTabs} current={floorId} onSelect={setFloorId} />
      <div style={{ flex: 1, minHeight: 0 }}>
        <FloorSvg plan={plan} floorId={floorId} scene={scene} health={state.health} onSelectRoom={setSelected} />
      </div>
      {fire && <PriorityList scene={scene} onSelect={setSelected} onMarkSearched={markSearched} />}
      {room && <RoomSheet room={room} entry={entry} onClose={() => setSelected(null)} onMarkSearched={markSearched} />}
    </div>
  );
}
