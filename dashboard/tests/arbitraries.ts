import fc from 'fast-check';
import type { CrewMessage, Floorplan, RoomStateCode, RoomStatesMessage } from '../src/types';
import plan from '../../hub/config/floorplan.json';

export const PLAN = plan as unknown as Floorplan;
export const ROOM_IDS = PLAN.floors.flatMap((f) => f.rooms.map((r) => r.id));
export const NOW = 1_730_000_000_000;

export const stateArb = fc.constantFrom<RoomStateCode>('MOTION', 'POSSIBLE', 'NO_DETECTION', 'UNKNOWN');
const bandArb = fc.constantFrom('high', 'medium', 'low' as const);

// Room ids include ones that are not on the floor plan, to exercise "Not on floor plan".
const idArb = fc.oneof(fc.constantFrom(...ROOM_IDS), fc.constantFrom('R9', 'X1'));

export const roomArb = (id: string) =>
  fc.record({
    room_id: fc.constant(id),
    state: stateArb,
    confidence_band: bandArb,
    confidence_pct: fc.integer({ min: 0, max: 100 }),
    last_seen: fc.option(fc.integer({ min: NOW / 1000 - 4000, max: NOW / 1000 }), { nil: null }),
    stale: fc.boolean(),
    last_known_state: fc.option(stateArb, { nil: null }),
    stale_age_s: fc.option(fc.integer({ min: 0, max: 5000 }), { nil: null }),
    calibrated: fc.boolean(),
    searched: fc.boolean(),
    annotation: fc.option(fc.constantFrom('responder_present', 'recent_motion_may_be_responder'), { nil: null }),
    alarm_time_state: fc.option(stateArb, { nil: null }),
    link_health: fc.constantFrom('ok', 'degraded', 'offline', 'tx_dead'),
    source: fc.constantFrom('edge', 'hub' as const),
  });

export const roomStatesArb: fc.Arbitrary<RoomStatesMessage> = fc
  .uniqueArray(idArb, { minLength: 0, maxLength: 8 })
  .chain((ids) =>
    fc.record({
      type: fc.constant('room_states' as const),
      ts: fc.constant(NOW / 1000),
      system_state: fc.constantFrom('IDLE', 'CALIBRATION', 'TEST', 'ALARM_ACTIVE' as const),
      simulated: fc.boolean(),
      rooms: fc.tuple(...ids.map(roomArb)),
      ranking: fc.shuffledSubarray(ids, { minLength: ids.length, maxLength: ids.length }),
    }),
  ) as fc.Arbitrary<RoomStatesMessage>;

export const crewArb: fc.Arbitrary<CrewMessage> = fc.record({
  type: fc.constant('crew' as const),
  ts: fc.constant(NOW / 1000),
  tags: fc.uniqueArray(
    fc.record({
      tag_id: fc.constantFrom('E1', 'E2', 'E3'),
      location_kind: fc.constantFrom('room', 'near', 'between', 'lost' as const),
      room_id: fc.option(fc.constantFrom(...ROOM_IDS), { nil: null }),
      near_rooms: fc.uniqueArray(fc.constantFrom(...ROOM_IDS), { maxLength: 2 }),
      confidence_band: bandArb,
      last_heard_s: fc.integer({ min: 0, max: 600 }),
      marker: fc.constantFrom('solid', 'hollow' as const),
    }),
    { maxLength: 3, selector: (t) => t.tag_id },
  ),
  floor_crew_counts: fc.constant({ F1: 1 }),
}) as fc.Arbitrary<CrewMessage>;
