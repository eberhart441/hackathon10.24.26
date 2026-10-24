import { useCallback, useEffect, useMemo, useRef, useState } from 'preact/hooks';
import type { Floorplan } from '../types';
import { AuthError, api, ensureToken, forgetToken, getMyTag, getToken, isLaptop } from '../api';
import { Store, systemState, type StoreState } from '../store';
import { WsClient } from '../ws/client';
import { validateFloorplan } from '../floorplan/validate';
import { buildSceneModel } from '../scene/model';
import { ALARM_RED, THEME_DEFAULT } from '../scene/palette';
import { Plan2D } from '../render2d/Plan2D';
import { View3D, webglAvailable } from '../render3d/View3D';
import { Header } from './Header';
import { PairScreen } from './Pair';
import { PriorityList } from './PriorityList';
import { HealthSheet, RoomSheet } from './Sheets';
import { LaptopBar } from './LaptopBar';
import { CrewIcon } from './icons';
import { PhoneView } from './PhoneView';

const PHONE_VIEW_FORCED = new URLSearchParams(location.search).get('view') === 'phone';

type Phase = 'boot' | 'pair' | 'ready' | 'plan-error' | 'offline';

const store = new Store();

function useStore(): StoreState {
  const [s, set] = useState(store.get());
  useEffect(() => store.subscribe(set), []);
  return s;
}

function useNow(ms = 1000): number {
  const [now, set] = useState(Date.now());
  useEffect(() => {
    const t = window.setInterval(() => set(Date.now()), ms);
    return () => window.clearInterval(t);
  }, [ms]);
  return now;
}

function useReducedMotion(): boolean {
  const q = '(prefers-reduced-motion: reduce)';
  const [r, set] = useState(() => window.matchMedia?.(q).matches ?? false);
  useEffect(() => {
    const m = window.matchMedia?.(q);
    if (!m) return;
    const on = () => set(m.matches);
    m.addEventListener('change', on);
    return () => m.removeEventListener('change', on);
  }, []);
  return r;
}

export function App() {
  const [phase, setPhase] = useState<Phase>('boot');
  const [plan, setPlan] = useState<Floorplan | null>(null);
  const [planErrors, setPlanErrors] = useState<string[]>([]);
  const [floorId, setFloorId] = useState('');
  const [roomOpen, setRoomOpen] = useState<string | null>(null);
  const [healthOpen, setHealthOpen] = useState(false);
  const [listOpen, setListOpen] = useState(false);
  const [use3d, setUse3d] = useState(() => webglAvailable());
  const [fallback, setFallback] = useState<string | null>(null);
  const [laptop, setLaptop] = useState(false);
  const [simTrigger, setSimTrigger] = useState(false);
  const [flash, setFlash] = useState(false);
  const [frameReq, setFrameReq] = useState<{ seq: number; rooms: string[] | null }>({ seq: 0, rooms: null });
  const [rotateSeq, setRotateSeq] = useState(0);
  const [snapshotBig, setSnapshotBig] = useState(false);
  const [boundTag, setBoundTag] = useState<string | null>(null); // the responder tag this phone's holder carries
  const ws = useRef<WsClient | null>(null);
  const s = useStore();
  const now = useNow();
  const reducedMotion = useReducedMotion();

  const goPair = useCallback(() => {
    ws.current?.stop();
    ws.current = null;
    forgetToken();
    store.reset();
    setPhase('pair');
  }, []);

  const start = useCallback(async () => {
    try {
      if (!(await ensureToken())) return setPhase('pair');
      const onLaptop = isLaptop() && (await api.whoami()).loopback;
      setLaptop(onLaptop);
      setBoundTag(onLaptop && !PHONE_VIEW_FORCED ? null : getMyTag());
      const result = validateFloorplan(await api.floorplan());
      if (!result.ok) {
        setPlanErrors(result.errors);
        return setPhase('plan-error');
      }
      setPlan(result.plan);
      setFloorId((f) => f || result.plan.floors[0].id);
      ws.current?.stop();
      ws.current = new WsClient(store, getToken, goPair);
      ws.current.start();
      setPhase('ready');
    } catch (e) {
      if (e instanceof AuthError) {
        // A laptop token dies with the hub process; ask for a new one instead of pairing.
        if (isLaptop()) return setPhase('offline');
        return goPair();
      }
      setPhase('offline');
    }
  }, [goPair]);

  useEffect(() => {
    start();
    return () => ws.current?.stop();
  }, []);

  // Offline at launch: keep retrying quietly so the app recovers when the hotspot comes back.
  useEffect(() => {
    if (phase !== 'offline') return;
    const t = window.setInterval(start, 3000);
    return () => window.clearInterval(t);
  }, [phase, start]);

  const model = useMemo(() => (plan ? buildSceneModel(plan, s, now, boundTag) : null), [plan, s, now, boundTag]);
  const sys = systemState(s);
  const alarm = sys === 'ALARM_ACTIVE';

  // Fire-mode entry: red header, flash, frame flagged rooms, open the list, wake lock (Kiro R13).
  const prevSys = useRef(sys);
  useEffect(() => {
    const was = prevSys.current;
    prevSys.current = sys;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', alarm ? ALARM_RED : THEME_DEFAULT);
    if (sys === 'ALARM_ACTIVE' && was !== 'ALARM_ACTIVE' && model) {
      if (!reducedMotion) {
        setFlash(true);
        window.setTimeout(() => setFlash(false), 1000);
      }
      const top = model.list.find((l) => !l.searched && l.floorId);
      if (top?.floorId) setFloorId(top.floorId);
      const floorOfTop = top?.floorId ?? floorId;
      setFrameReq((r) => ({ seq: r.seq + 1, rooms: model.list.filter((l) => l.floorId === floorOfTop).map((l) => l.roomId) }));
      setListOpen(true);
      requestWakeLock();
    }
    if (sys !== 'ALARM_ACTIVE' && was === 'ALARM_ACTIVE') {
      setSimTrigger(false);
      setRoomOpen(null);
      releaseWakeLock();
    }
  }, [sys]);

  const markSearched = useCallback(async (roomId: string) => {
    try {
      await api.markSearched(roomId);
    } catch (e) {
      if (e instanceof AuthError) goPair();
    }
  }, [goPair]);

  const header = (
    <Header
      paired={phase === 'ready'}
      recording={s.recording}
      health={s.health}
      alarm={alarm}
      simulated={!!s.roomStates?.simulated}
      simulatedTrigger={simTrigger}
      onHealth={() => setHealthOpen(true)}
    />
  );

  if (phase === 'boot') return <div class="app">{header}<main class="center-screen"><p>Connecting to the hub…</p></main></div>;
  if (phase === 'pair') return <div class="app">{header}<PairScreen onPaired={start} /></div>;
  if (phase === 'offline')
    return (
      <div class="app">
        {header}
        <div class="banner hub-lost" role="alert">Hub not reachable. Check the laptop hotspot and that the hub is running. Retrying…</div>
      </div>
    );
  if (phase === 'plan-error')
    return (
      <div class="app">
        {header}
        <main class="center-screen">
          <div class="plan-errors" role="alert">
            <h1>The floor plan file has problems</h1>
            <p>Fix <code>hub/config/floorplan.json</code>, then reload. Nothing is drawn until it is valid.</p>
            <ul>{planErrors.map((e) => <li key={e}>{e}</li>)}</ul>
          </div>
        </main>
      </div>
    );
  if (!plan || !model) return null;

  // Phones get the simple responder view; the laptop keeps the presenter view (?view=phone forces it).
  if (!laptop || PHONE_VIEW_FORCED) {
    return (
      <>
        {flash ? <div class="flash" aria-hidden="true" /> : null}
        <PhoneView plan={plan} model={model} floorId={floorId} />
      </>
    );
  }

  const room = roomOpen ? model.rooms.find((r) => r.id === roomOpen) : null;
  const offFloorChips = model.crewChips.filter((c) => c.floorId !== floorId);
  const show3d = use3d && !fallback;

  return (
    <div class={`app${alarm ? ' alarm' : ''}`}>
      {flash ? <div class="flash" aria-hidden="true" /> : null}
      {header}
      {model.hubLost ? (
        <div class="banner hub-lost" role="alert">
          HUB LOST — no update for {model.hubLostAgeText ?? 'a while'}. Showing last known states only.
        </div>
      ) : s.reconnecting ? (
        <div class="banner info" role="status">Reconnecting…</div>
      ) : null}
      {model.allSearched ? <div class="banner sweep" role="status">No detection rooms still require a sweep.</div> : null}
      {laptop ? <LaptopBar alarm={alarm} idle={sys === 'IDLE'} onTriggered={(sim) => setSimTrigger(sim)} onEnded={() => setSimTrigger(false)} /> : null}

      <nav class="floor-tabs" aria-label="Floors">
        {model.floors.map((f) => (
          <button
            type="button"
            key={f.id}
            class={`tab${f.id === floorId ? ' on' : ''}`}
            aria-pressed={f.id === floorId}
            onClick={() => setFloorId(f.id)}
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

      <div class="body">
        <section class="plan" aria-label="Floor plan">
          {show3d ? (
            <View3D
              plan={plan}
              model={model}
              floorId={floorId}
              onRoomTap={setRoomOpen}
              onFallback={setFallback}
              frameRequest={frameReq}
              rotateSeq={rotateSeq}
              reducedMotion={reducedMotion}
            />
          ) : (
            <Plan2D plan={plan} model={model} floorId={floorId} onRoomTap={setRoomOpen} />
          )}
          <div class="plan-tools">
            {show3d ? (
              <button type="button" class="tool" onClick={() => setRotateSeq((n) => n + 1)} aria-label="Rotate view">
                ⟳
              </button>
            ) : null}
            {!fallback && webglAvailable() ? (
              <button type="button" class="tool" onClick={() => setUse3d((v) => !v)} aria-label={use3d ? 'Switch to 2D view' : 'Switch to 3D view'}>
                {use3d ? '2D' : '3D'}
              </button>
            ) : null}
          </div>
          {fallback ? <div class={`fallback-note${alarm ? ' below-snapshot' : ''}`}>2D view · {fallback}</div> : null}
          {offFloorChips.length ? (
            <div class="chip-row">
              {offFloorChips.map((c) => (
                <span class="crew-chip" key={c.tagId}>{c.text}</span>
              ))}
            </div>
          ) : null}
          {alarm ? (
            <div
              role="button"
              tabIndex={0}
              class={`snapshot${snapshotBig ? ' big' : ''}`}
              onClick={() => setSnapshotBig((v) => !v)}
              aria-label={snapshotBig ? 'Shrink alarm-time snapshot' : 'Enlarge alarm-time snapshot'}
            >
              <span class="snapshot-title">AT ALARM</span>
              <Plan2D plan={plan} model={model} floorId={floorId} onRoomTap={() => undefined} snapshot />
            </div>
          ) : null}
        </section>

        {model.occupancyShown ? (
          <PriorityList items={model.list} expanded={listOpen} onToggle={() => setListOpen((v) => !v)} onRoom={setRoomOpen} onSearched={markSearched} />
        ) : (
          <section class="idle-panel">
            <h2>Normal mode</h2>
            <p>No incident is open. Room states are only shown after an alarm. Sensor links and node health are live.</p>
          </section>
        )}
      </div>

      {room ? <RoomSheet room={room} onClose={() => setRoomOpen(null)} onSearched={markSearched} /> : null}
      {healthOpen ? <HealthSheet health={s.health} onClose={() => setHealthOpen(false)} /> : null}
    </div>
  );
}

// Screen Wake Lock is best effort; iOS supports it in an installed PWA from 18.4 (Kiro R13.4).
let lock: { release: () => Promise<void> } | null = null;
async function requestWakeLock() {
  try {
    const nav = navigator as Navigator & { wakeLock?: { request: (t: 'screen') => Promise<{ release: () => Promise<void> }> } };
    lock = (await nav.wakeLock?.request('screen')) ?? null;
  } catch {
    lock = null;
  }
}
function releaseWakeLock() {
  lock?.release().catch(() => undefined);
  lock = null;
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && systemState(store.get()) === 'ALARM_ACTIVE') requestWakeLock();
});
