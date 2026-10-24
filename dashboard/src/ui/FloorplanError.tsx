// Floor-plan error screen (Req 6.4, 10.1). Shown instead of the floor plan when it fails to load.
import type { FloorplanError as FpError } from "../floorplan/types";
import { STRINGS } from "../scene/strings";

export function FloorplanError({ errors }: { errors: FpError[] | string }) {
  const messages = typeof errors === "string" ? [errors] : errors.map((e) => e.message);
  return (
    <main>
      <p role="note">{STRINGS.disclaimer}</p>
      <h1>{STRINGS.floorPlanErrorTitle}</h1>
      <p>{STRINGS.floorPlanErrorHelp}</p>
      <ul>
        {messages.map((m, i) => (
          <li key={i}>{m}</li>
        ))}
      </ul>
    </main>
  );
}
