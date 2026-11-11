// Light links in 3D: the blue links of the lighting sheet (E-LINK) lifted under the ceiling.
// The sheet holds them as paths in its mm; the sheet model (docs/epd-format.md: sheet x = k·x + tx,
// sheet y = ty − k·y) turns them back into model mm. A switch link also drops from the ceiling
// to its switch on the wall (the switch position comes from the scene), so the link reads as
// "switch → up → along the ceiling → lights".

import { linkEnds } from "@/engine/sheet/views";
import type { Page, Scene, XYZ } from "@/shared/types";

export const LINK_LAYER = "E-LINK";
const BELOW_CEILING = 40;  // mm: the links run just under the ceiling, not inside it

export interface LightLink3D {
  key: string;        // switch_link:<id> or light_set:<ids>
  ends: string[];     // point:<id> of its switch or lights (views.linkEnds)
  color: string;
  lines: XYZ[][];     // polylines in model mm
}

// Polylines of a path: "M x y L x y …"; a new M starts a new polyline, joined if it continues the last
export function pathLines(d: string): [number, number][][] {
  const out: [number, number][][] = [];
  for (const m of d.matchAll(/([ML])\s*(-?\d*\.?\d+(?:e-?\d+)?)[\s,]+(-?\d*\.?\d+(?:e-?\d+)?)/gi)) {
    const p: [number, number] = [+m[2], +m[3]];
    const last = out[out.length - 1];
    const tail = last?.[last.length - 1];
    if (m[1].toUpperCase() === "L" && last) last.push(p);
    else if (tail && tail[0] === p[0] && tail[1] === p[1]) continue;  // M at the end of the last line
    else out.push([p]);
  }
  return out.filter((l) => l.length > 1);
}

// The links of the lighting sheet in model mm, under the ceiling of the scene
export function lightLinks(page: Page | undefined, scene: Scene): LightLink3D[] {
  const model = page?.model;
  if (!page || !model) return [];
  const [k, tx, ty] = model;
  const z = scene.ceiling - BELOW_CEILING;
  const out: LightLink3D[] = [];
  for (const it of page.items) {
    if (it.l !== LINK_LAYER || !it.o) continue;
    const ends = linkEnds(it.o);
    if (!ends) continue;
    const lines: XYZ[][] = pathLines(it.d).map((l) => l.map(([x, y]) => [(x - tx) / k, (ty - y) / k, z] as XYZ));
    if (!lines.length) continue;
    if (it.o.startsWith("switch_link:")) {
      const sw = scene.points[it.o.slice(12)];
      if (sw) {
        const [x, y, h] = sw.pos;
        // The path starts at the switch symbol, which stands off the wall: join its nearer end
        const last = lines[lines.length - 1];
        const near = [lines[0][0], last[last.length - 1]]
          .sort((a, b) => Math.hypot(a[0] - x, a[1] - y) - Math.hypot(b[0] - x, b[1] - y))[0];
        lines.unshift([[x, y, h], [x, y, z], near]);
      }
    }
    out.push({ key: it.o, ends, color: it.c, lines });
  }
  return out;
}
