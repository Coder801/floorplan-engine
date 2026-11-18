// Floor heating in 3D (scene.heating, epd/heating_scene.py): which sheet layer each part of a
// zone follows, and what feeds the controllers. The floor heating tab shows only its own layers,
// so the controller (a point of the electrical sheet) and its line from the panel would be hidden
// there; they follow the cold lead layer instead: the lead goes on from the controller.

import type { Scene } from "@/shared/types";

export const HEAT_LAYER = {
  area: "E-FLOORHEAT-ZONE",
  cable: "E-FLOORHEAT",
  lead: "E-FLOORHEAT-LEAD",
  sensor: "E-FLOORHEAT-SENSOR",
} as const;

// Controllers of the zones and the lines and boxes from the panel to them: point:, wire:, box: keys
export function heatingFeed(scene: Scene): Set<string> {
  const out = new Set<string>();
  for (const z of Object.values(scene.heating ?? {})) {
    out.add(`point:${z.thermostat}`);
    for (const w of z.feed.wires) out.add(`wire:${w}`);
    for (const b of z.feed.boxes) out.add(`box:${b}`);
  }
  return out;
}
