// Floor highlight on the plan sheet (decision 2026-11-11): the floor of the room or zone under the
// cursor (page.floors, epd objects.plan_floor_rings) fills with the highlight colour, fading in
// and out; walls and the area outline stay as they are.

import type { XY } from "@/shared/types";

export const FLOOR_ALPHA = 0.16;  // fill opacity of a fully shown floor
export const FLOOR_FADE_MS = 180;

// Move each floor's share (0…1) towards its target: 1 for the lit ones, 0 for the rest; a floor
// that faded out is dropped. Returns true while something is still moving
export function stepFades(fades: Map<string, number>, lit: ReadonlySet<string>, dt: number, ms = FLOOR_FADE_MS): boolean {
  const step = ms > 0 ? dt / ms : 1;
  for (const key of lit) if (!fades.has(key)) fades.set(key, 0);
  let moving = false;
  for (const [key, share] of fades) {
    const next = lit.has(key) ? Math.min(1, share + step) : Math.max(0, share - step);
    if (next === 0 && !lit.has(key)) { fades.delete(key); continue; }
    fades.set(key, next);
    if (next !== (lit.has(key) ? 1 : 0)) moving = true;
  }
  return moving;
}

export function floorPath(rings: XY[][]): Path2D {
  const path = new Path2D();
  for (const ring of rings) {
    ring.forEach(([x, y], i) => (i ? path.lineTo(x, y) : path.moveTo(x, y)));
    path.closePath();
  }
  return path;
}
