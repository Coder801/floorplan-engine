// Engineering grid under the drawing (decision 2026-11-13): faint squares over the whole block
// show where the drawing is and where the page is; the flat itself stays on plain paper. The grid
// is tied to the model (a square is a round number of mm) and moves and zooms with the drawing.
// Screen only: PNG and print have none.

import { isDark, palette } from "@/shared/palette";
import type { Item, XY } from "@/shared/types";
import { shiftOf, sceneOf, type Drawing } from "./drawing";

export const GRID_MIN_PX = 12;   // a square is never smaller on screen
export const GRID_MAJOR = 5;     // every fifth line is stronger
export const GRID_ALPHA = 0.05;  // of the ink colour; a major line is twice that

// Side of a square in mm: the smallest of 1-2-5 × 10ⁿ that is at least GRID_MIN_PX on screen
export function gridStep(pxPerMm: number, minPx = GRID_MIN_PX): number {
  const need = minPx / pxPerMm;
  const pow = 10 ** Math.floor(Math.log10(need));
  return [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= need * (1 - 1e-9))!;
}

// Screen positions (px) of the grid lines along one axis: origin is where mm 0 is on screen, step
// the side of a square in px; major marks the lines that fall on every GRID_MAJOR-th square
export function gridLines(origin: number, step: number, size: number): { at: number; major: boolean }[] {
  const out: { at: number; major: boolean }[] = [];
  for (let i = Math.ceil(-origin / step); origin + i * step <= size; i++) {
    out.push({ at: Math.round(origin + i * step), major: i % GRID_MAJOR === 0 });
  }
  return out;
}

// The grid over the whole canvas, in device px with no transform set: (ox, oy) is where mm 0 is,
// step the side of a square; lines are one device pixel, on the pixel grid (sheet and elevation)
export function paintGrid(ctx: CanvasRenderingContext2D, ox: number, oy: number, step: number) {
  const { width, height } = ctx.canvas;
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = isDark() ? palette.ink : "#000000";
  for (const { at, major } of gridLines(ox, step, width)) {
    ctx.globalAlpha = major ? 2 * GRID_ALPHA : GRID_ALPHA;
    ctx.fillRect(at, 0, 1, height);
  }
  for (const { at, major } of gridLines(oy, step, height)) {
    ctx.globalAlpha = major ? 2 * GRID_ALPHA : GRID_ALPHA;
    ctx.fillRect(0, at, width, 1);
  }
  ctx.restore();
}

// A room's ceiling or floor plane on an elevations sheet (drawing/ceilings.py) has no data, only
// primitives: its paper is the largest closed outline on the elevation layer — the room with its
// walls. Fills (text) and open lines are not outlines
export function planeRing(items: readonly Item[]): XY[] | null {
  let best: XY[] | null = null, most = 0;
  for (const it of items) {
    if (it.k !== "s" || it.l !== "E-ELEV" || (it.d.match(/M/g) ?? []).length !== 1) continue;
    const n = (it.d.match(/-?\d*\.?\d+(?:e-?\d+)?/gi) ?? []).map(Number);
    const ring: XY[] = [];
    for (let i = 0; i + 1 < n.length; i += 2) ring.push([n[i], n[i + 1]]);
    const a = ring[0], b = ring[ring.length - 1];
    if (ring.length < 4 || (!/Z\s*$/i.test(it.d) && (a[0] !== b[0] || a[1] !== b[1]))) continue;
    const xs = ring.map((p) => p[0]), ys = ring.map((p) => p[1]);
    const size = (Math.max(...xs) - Math.min(...xs)) * (Math.max(...ys) - Math.min(...ys));
    if (size > most) { most = size; best = ring; }
  }
  return best;
}

// What stays plain paper, in mm of the base sheet: the floor slab of the flat (under the walls and
// in the openings too); an older build without the slab has the room floors of the plan sheet.
// On an elevations sheet cut down to one view (a ceiling or floor plane, walls.ts wallSheet) — the
// room of the plane; a whole sheet with many views has no paper
export function paperRings(d: Drawing): XY[][] {
  if (d.base.stage === "elevations") {
    const views = new Set(d.base.items.map((it) => it.o).filter((o) => o?.startsWith("elevation:")));
    const ring = views.size === 1 ? planeRing(d.base.items) : null;
    return ring ? [ring] : [];
  }
  const model = d.base.model, slab = sceneOf(d)?.slab;
  if (model && slab?.length) {
    const [k, tx, ty] = model;
    return slab.map((ring) => ring.map(([x, y]): XY => [k * x + tx, ty - k * y]));
  }
  const plan = d.pages.find((p) => p.floors);
  if (!plan?.floors) return [];
  const { f, dx, dy } = shiftOf(plan, d.base);
  return Object.values(plan.floors).flatMap((rings) => rings.slice(0, 1))
    .map((ring) => ring.map(([x, y]): XY => [f * x + dx, f * y + dy]));
}
