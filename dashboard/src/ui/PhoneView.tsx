import type { Floorplan } from '../types';
import type { SceneModel } from '../scene/model';
import { Plan2D } from '../render2d/Plan2D';

interface Props {
  plan: Floorplan;
  model: SceneModel;
  floorId: string;
}

// The responder's phone: the floor plan and nothing else. Every room carries its own name, search
// priority and state; the responder's own tag shows as YOU in the room it was located in. No
// buttons, no text outside the rooms. The laptop keeps the full presenter view.
export function PhoneView({ plan, model, floorId }: Props) {
  // Follow the responder's own floor, else the floor of the first room still to search.
  const shown = model.you?.floorId ?? model.list.find((l) => !l.searched && l.floorId)?.floorId ?? floorId;
  return (
    <main class={`app phone${model.alarm ? ' alarm' : ''}`} aria-label="Floor plan">
      <Plan2D plan={plan} model={model} floorId={shown} onRoomTap={() => undefined} minimal />
    </main>
  );
}
