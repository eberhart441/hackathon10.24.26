---
inclusion: fileMatch
fileMatchPattern: "dashboard/**"
---

# Dashboard UI steering

Source of truth for values: `dashboard/src/scene/palette.ts` (fills, labels, `STATE_PATTERN`, crew palette, band saturation) and `dashboard/src/ui/icons.tsx`. Change those files, not hard-coded copies.

## State_Palette and encoding

Every state uses fill + pattern + icon + label together. Color is never the only cue. Never use green for any state.

| State | Fill | Pattern | Icon | Label |
|---|---|---|---|---|
| MOTION | `#FF4D2E` | solid | wave | MOTION |
| POSSIBLE | `#FFB020` | 45° hatch | outline question | POSSIBLE |
| UNKNOWN | `#6E6596` | crosshatch + static noise | question | UNKNOWN |
| NO_DETECTION | `#3A4250` | dots | dash | NO DETECTION |

- UNKNOWN is `#6E6596`, not the plan's `#8A7FB8`: the darker value keeps every state pair distinguishable in grayscale (contrast ≥ 1.4).
- Confidence band scales saturation only (high 1, medium 0.75, low 0.5); hue stays fixed.
- Text/background pairs are ≥ 4.5:1. Text on POSSIBLE is `#111111`.

## Crew_Palette

Crew markers use only `#FFFFFF` and `#111111` (solid / hollow). Never a state color.

## Wording

- Banned_Words: `/\b(empty|clear(ed)?|safe)\b/i`. No UI string, label, or aria text may match.
- Use "Search priority" for the ranked list and "Motion last seen" for timestamps.
- No person figures, footprints, heatmaps, trails, smoke, or fire graphics.

## Interaction

- Touch targets are ≥ 56 px in both dimensions.
- End incident and the alarm trigger are laptop-only. Never show them on the tablet/crew view.

## Data rules

- The server ranking is truth. The client never re-ranks rooms or recomputes state, band, or confidence. Render what the hub sends.
- No occupancy data in browser storage (localStorage, sessionStorage, IndexedDB, Cache API). The only stored keys are `beacon.token` (pairing token) and `beacon.tag` (the responder tag this phone is bound to) in localStorage.
