import { describe, expect, it } from 'vitest';
import fc from 'fast-check';
import { buildSceneModel, HUB_LOST_MS, type SceneModel } from '../src/scene/model';
import { applyMessage, emptyStore, type StoreState } from '../src/store';
import { CREW_PALETTE, STATE_FILL } from '../src/scene/palette';
import { NOW, PLAN, crewArb, roomStatesArb } from './arbitraries';

const RUNS = { numRuns: 200 };
const BANNED = /\b(empty|clear(ed)?|safe)\b/i;
const LABELS = new Set(['MOTION', 'POSSIBLE', 'UNKNOWN', 'NO DETECTION']);

function storeWith(parts: Partial<StoreState>, lastMessageAt: number | null = NOW): StoreState {
  return { ...emptyStore(), ...parts, lastMessageAt };
}

function visibleText(m: SceneModel): string[] {
  const out: string[] = [];
  for (const r of m.rooms) {
    out.push(r.name, r.ariaLabel);
    const o = r.occupancy;
    if (o) out.push(o.label, o.confText, o.detailText ?? '', o.subLabel ?? '', o.annotation ?? '', o.alarmTimeLabel ?? '');
    for (const c of r.crew) out.push(c.text);
  }
  for (const l of m.list) out.push(l.name, l.label, l.confText, l.detailText ?? '', l.note ?? '');
  for (const c of m.crewChips) out.push(c.text);
  return out;
}

// Feature: pwa-dashboard. Properties mirror Kiro R8, R9, R12, R14, R15.
describe('scene model properties', () => {
  it('P-UI1: every label is one of the four states and no banned word is ever shown', () => {
    fc.assert(
      fc.property(roomStatesArb, crewArb, fc.integer({ min: 0, max: 20_000 }), (rs, crew, age) => {
        const m = buildSceneModel(PLAN, storeWith({ roomStates: rs, crew }, NOW - age), NOW);
        for (const r of m.rooms) if (r.occupancy) expect(LABELS.has(r.occupancy.label)).toBe(true);
        for (const l of m.list) expect(LABELS.has(l.label)).toBe(true);
        for (const t of visibleText(m)) expect(t).not.toMatch(BANNED);
      }),
      RUNS,
    );
  });

  it('P-UI2: the priority list is the server ranking filtered to flagged rooms, ranks 1..n', () => {
    fc.assert(
      fc.property(roomStatesArb, (rs) => {
        const m = buildSceneModel(PLAN, storeWith({ roomStates: rs }), NOW);
        if (!['ALARM_ACTIVE', 'TEST'].includes(rs.system_state)) {
          expect(m.list).toEqual([]);
          return;
        }
        const byId = new Map(rs.rooms.map((r) => [r.room_id, r]));
        const expected = rs.ranking.filter((id) => byId.has(id) && byId.get(id)!.state !== 'NO_DETECTION');
        expect(m.list.map((l) => l.roomId)).toEqual(expected);
        m.list.forEach((l, i) => expect(l.rank).toBe(i + 1));
        expect(m.list.filter((l) => l.isTop).length).toBeLessThanOrEqual(1);
        if (m.list.some((l) => l.isTop)) expect(m.list[0].isTop).toBe(true);
      }),
      RUNS,
    );
  });

  it('P-UI3: crew never uses a state colour and low confidence never lands in a single room', () => {
    fc.assert(
      fc.property(roomStatesArb, crewArb, (rs, crew) => {
        const alarmRs = { ...rs, system_state: 'ALARM_ACTIVE' as const };
        const m = buildSceneModel(PLAN, storeWith({ roomStates: alarmRs, crew }), NOW);
        for (const c of CREW_PALETTE) expect(Object.values(STATE_FILL)).not.toContain(c);
        for (const t of crew.tags) {
          const solidInRoom = m.rooms.some((r) => r.crew.some((c) => c.tagId === t.tag_id && !c.hollow));
          if (t.confidence_band === 'low' && t.marker === 'solid') expect(solidInRoom).toBe(false);
          if (t.location_kind === 'near' || t.location_kind === 'between') expect(solidInRoom).toBe(false);
        }
      }),
      RUNS,
    );
  });

  it('P-UI4: stale or uncalibrated rooms always get the UNKNOWN treatment', () => {
    fc.assert(
      fc.property(roomStatesArb, (rs) => {
        const alarmRs = { ...rs, system_state: 'ALARM_ACTIVE' as const };
        const m = buildSceneModel(PLAN, storeWith({ roomStates: alarmRs }), NOW);
        for (const msg of alarmRs.rooms) {
          const r = m.rooms.find((x) => x.id === msg.room_id);
          if (!r) continue;
          if (msg.stale || !msg.calibrated) expect(r.occupancy!.state).toBe('UNKNOWN');
          if (msg.stale && msg.last_known_state) expect(r.occupancy!.detailText).toMatch(/^last known /);
        }
      }),
      RUNS,
    );
  });

  it('P-UI5: 5 s without a message greys every room and raises hub-lost', () => {
    fc.assert(
      fc.property(roomStatesArb, fc.integer({ min: HUB_LOST_MS, max: 600_000 }), (rs, age) => {
        const alarmRs = { ...rs, system_state: 'ALARM_ACTIVE' as const };
        const m = buildSceneModel(PLAN, storeWith({ roomStates: alarmRs }, NOW - age), NOW);
        expect(m.hubLost).toBe(true);
        for (const r of m.rooms) {
          expect(r.greyed).toBe(true);
          expect(r.occupancy!.stale).toBe(true);
        }
      }),
      RUNS,
    );
  });

  it('IDLE shows architecture only, even if a message carries rooms (Kiro R14.2)', () => {
    fc.assert(
      fc.property(roomStatesArb, crewArb, (rs, crew) => {
        const idle = { ...rs, system_state: 'IDLE' as const };
        const m = buildSceneModel(PLAN, storeWith({ roomStates: idle, crew }), NOW);
        for (const r of m.rooms) {
          expect(r.occupancy).toBeNull();
          expect(r.crew).toEqual([]);
        }
        expect(m.list).toEqual([]);
        expect(m.crewChips).toEqual([]);
      }),
      RUNS,
    );
  });

  it('the model is a pure function of its inputs', () => {
    fc.assert(
      fc.property(roomStatesArb, crewArb, (rs, crew) => {
        const s = storeWith({ roomStates: rs, crew });
        expect(buildSceneModel(PLAN, s, NOW)).toEqual(buildSceneModel(PLAN, s, NOW));
      }),
      { numRuns: 100 },
    );
  });
});

describe('scene model examples', () => {
  const base = {
    type: 'room_states' as const,
    ts: NOW / 1000,
    system_state: 'ALARM_ACTIVE' as const,
    simulated: true,
  };
  const room = (id: string, state: 'MOTION' | 'NO_DETECTION', searched = false) => ({
    room_id: id,
    state,
    confidence_band: 'high' as const,
    confidence_pct: 90,
    last_seen: NOW / 1000 - 42,
    stale: false,
    last_known_state: null,
    stale_age_s: null,
    calibrated: true,
    searched,
    annotation: null,
    alarm_time_state: state,
    link_health: 'ok',
  });

  it('a plan room missing from an alarm message shows "No data from hub" (Kiro R8.4)', () => {
    const m = buildSceneModel(PLAN, storeWith({ roomStates: { ...base, rooms: [room('R1', 'MOTION')], ranking: ['R1'] } }), NOW);
    expect(m.rooms.find((r) => r.id === 'R2')!.occupancy!.detailText).toBe('No data from hub');
    expect(m.rooms.find((r) => r.id === 'R1')!.occupancy!.detailText).toBe('Motion last seen 0:42 ago');
  });

  it('NO DETECTION rooms say they still need a sweep, and all-searched raises the reminder', () => {
    const rs = { ...base, rooms: [room('R1', 'MOTION', true), room('R2', 'NO_DETECTION')], ranking: ['R1', 'R2'] };
    const m = buildSceneModel(PLAN, storeWith({ roomStates: rs }), NOW);
    expect(m.rooms.find((r) => r.id === 'R2')!.occupancy!.subLabel).toBe('Still needs a sweep');
    expect(m.allSearched).toBe(true);
    expect(m.list[0].isTop).toBe(false);
  });

  it('a ranked room that is not on the plan is still listed with a note (Kiro R8.5)', () => {
    const rs = { ...base, rooms: [room('R9', 'MOTION')], ranking: ['R9'] };
    const m = buildSceneModel(PLAN, storeWith({ roomStates: rs }), NOW);
    expect(m.list[0]).toMatchObject({ roomId: 'R9', note: 'Not on floor plan', rank: 1 });
  });

  it('a room with no receiver says so (hub annotation no_sensors)', () => {
    const r2 = { ...room('R2', 'MOTION'), state: 'UNKNOWN' as const, calibrated: false, last_seen: null, annotation: 'no_sensors' };
    const m = buildSceneModel(PLAN, storeWith({ roomStates: { ...base, rooms: [r2], ranking: ['R2'] } }), NOW);
    const o = m.rooms.find((r) => r.id === 'R2')!.occupancy!;
    expect([o.label, o.annotation, o.rank]).toEqual(['UNKNOWN', 'No sensors in this room', 1]);
  });

  describe('"You are here": the phone bound to a tag (parent Req 26.4)', () => {
    const tag = (tag_id: string, over: object = {}) => ({
      tag_id, location_kind: 'room' as const, room_id: 'HALL', near_rooms: [], confidence_band: 'high' as const,
      last_heard_s: 1, marker: 'solid' as const, ...over,
    });
    const crew = (...tags: ReturnType<typeof tag>[]) => ({ type: 'crew' as const, ts: 0, tags, floor_crew_counts: {} });
    const rs = { ...base, rooms: [room('R1', 'MOTION')], ranking: ['R1'] };

    it('marks only the bound tag as you, in the room it was located in', () => {
      const m = buildSceneModel(PLAN, storeWith({ roomStates: rs, crew: crew(tag('E1'), tag('E2', { room_id: 'R1' })) }), NOW, 'E1');
      expect(m.you).toEqual({ tagId: 'E1', roomIds: ['HALL'], floorId: 'F1', lost: false });
      expect(m.rooms.find((r) => r.id === 'HALL')!.crew).toMatchObject([{ tagId: 'E1', you: true }]);
      expect(m.rooms.find((r) => r.id === 'R1')!.crew).toMatchObject([{ tagId: 'E2', you: false }]);
    });

    it('low confidence stays two rooms, a lost tag stays where it was last heard, nothing without a binding', () => {
      const near = tag('E1', { location_kind: 'near', room_id: null, near_rooms: ['R1', 'HALL'], confidence_band: 'low' });
      let m = buildSceneModel(PLAN, storeWith({ roomStates: rs, crew: crew(near) }), NOW, 'E1');
      expect(m.you!.roomIds).toEqual(['R1', 'HALL']);
      expect(m.crewChips).toMatchObject([{ tagId: 'E1', you: true }]);
      const lost = tag('E1', { location_kind: 'lost', room_id: 'R1', marker: 'hollow', last_heard_s: 30 });
      m = buildSceneModel(PLAN, storeWith({ roomStates: rs, crew: crew(lost) }), NOW, 'E1');
      expect(m.you).toMatchObject({ roomIds: ['R1'], lost: true });
      expect(buildSceneModel(PLAN, storeWith({ roomStates: rs, crew: crew(tag('E1')) }), NOW, null).you).toBeNull();
      const idle = { ...rs, system_state: 'IDLE' as const, rooms: [], ranking: [] };
      expect(buildSceneModel(PLAN, storeWith({ roomStates: idle, crew: crew(tag('E1')) }), NOW, 'E1').you).toBeNull();
    });
  });

  it('leaving an incident drops every room and crew entry from the store (Kiro R14.4)', () => {
    let s = emptyStore();
    s = applyMessage(s, { ...base, rooms: [room('R1', 'MOTION')], ranking: ['R1'] }, NOW);
    s = applyMessage(s, { type: 'crew', ts: 0, tags: [], floor_crew_counts: {} }, NOW);
    s = applyMessage(s, { ...base, system_state: 'IDLE', rooms: [room('R1', 'MOTION')], ranking: ['R1'] }, NOW);
    expect(s.roomStates!.rooms).toEqual([]);
    expect(s.crew).toBeNull();
  });
});

describe('phone view data', () => {
  const msg = (ts: number, state: 'MOTION' | 'POSSIBLE', system: 'ALARM_ACTIVE' | 'IDLE' = 'ALARM_ACTIVE') => ({
    type: 'room_states' as const,
    ts,
    system_state: system,
    simulated: false,
    rooms: [{ room_id: 'R1', state, confidence_band: 'high' as const, confidence_pct: 90, last_seen: ts, stale: false,
      last_known_state: null, stale_age_s: null, calibrated: true, searched: false, annotation: null,
      alarm_time_state: null, link_health: 'ok' }],
    ranking: ['R1'],
  });

  it('history keeps the last five minutes of the incident and is wiped when it ends', () => {
    let s = emptyStore();
    for (let t = 0; t < 400; t++) s = applyMessage(s, msg(1000 + t, t < 200 ? 'MOTION' : 'POSSIBLE'), NOW);
    const h = s.history.R1;
    expect(h[h.length - 1][0] - h[0][0]).toBeLessThanOrEqual(300);
    expect(h.at(-1)![1]).toBe('POSSIBLE');
    s = applyMessage(s, msg(1400, 'POSSIBLE', 'IDLE'), NOW);
    expect(s.history).toEqual({});
  });

  it('ordered lists every plan room in the hub ranking order, unranked rooms after', () => {
    fc.assert(
      fc.property(roomStatesArb, (rs) => {
        const alarmRs = { ...rs, system_state: 'ALARM_ACTIVE' as const };
        const m = buildSceneModel(PLAN, storeWith({ roomStates: alarmRs }), NOW);
        expect(m.ordered.map((r) => r.id).sort()).toEqual(m.rooms.map((r) => r.id).sort());
        const ranked = alarmRs.ranking.filter((id) => m.rooms.some((r) => r.id === id));
        expect(m.ordered.slice(0, ranked.length).map((r) => r.id)).toEqual(ranked);
      }),
      RUNS,
    );
  });
});
