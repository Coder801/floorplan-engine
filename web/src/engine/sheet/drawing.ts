// One drawing for the sheets with a plan (plan, electrical, lighting, wiring, plumbing): the
// primitives of all sheets in the coordinates of one sheet (base, the first in order), via
// their model. A layer comes from the first sheet that has it in its viewport: walls and
// dimensions from the plan, points from electrical, links from lighting, cables from wiring;
// the same layers on other sheets are copies and are not repeated.
// A sheet tab is a set of its layers (own): switching tabs changes layers, not the drawing,
// and zoom and pan stay. Layers from other sheets are turned on in "Layers" (store.extra).

import { SHEET_ONLY } from "@/shared/consts";
import type { Box, Item, ObjectCard, Page, Scene } from "@/shared/types";
import { bbox, inView, viewOf } from "./paint";

// Sheets of one drawing (plumbing too: walls from the plan, pipes are its own layers); the
// panel, elevations and schedule stand alone
export const DRAWING_STAGES = new Set(["plan", "electrical", "lighting", "wiring", "plumbing"]);

// From the source sheet to base: x' = f·x + dx, y' = f·y + dy (sheet mm)
export interface Shift { f: number; dx: number; dy: number }

export const IDENTITY: Shift = { f: 1, dx: 0, dy: 0 };

export interface DrawingItem extends Item {
  box: Box;       // bounding box already on base
  shift: Shift;   // path d is still in its own sheet's mm
}

export interface Drawing {
  base: Page;
  pages: Page[];
  items: DrawingItem[];
  own: Map<Page, Set<string>>;     // layers the sheet shows itself
  view: Box;                       // viewports of all sheets on base
  objects: Record<string, ObjectCard>;  // cards of all sheets, for layers from another sheet
}

// sheet x = k·x + tx, sheet y = ty − k·y (docs/epd-format.md, model): the model is shared,
// so sheet → sheet is a scale and an offset
export function shiftOf(from: Page, to: Page): Shift {
  if (from === to || !from.model || !to.model) return IDENTITY;
  const [ks, txs, tys] = from.model, [kb, txb, tyb] = to.model;
  const f = kb / ks;
  return { f, dx: txb - f * txs, dy: tyb - f * tys };
}

export const shiftBox = ([x0, y0, x1, y1]: Box, { f, dx, dy }: Shift): Box =>
  [f * x0 + dx, f * y0 + dy, f * x1 + dx, f * y1 + dy];

// Sheets without model (panel, elevations) are not merged into the shared drawing: a drawing of one sheet
export function buildDrawing(pages: Page[]): Drawing {
  const sheets = pages.length > 1 && pages.every((p) => p.model) ? pages : pages.slice(0, 1);
  const base = sheets[0];
  const items: DrawingItem[] = [];
  const own = new Map<Page, Set<string>>();
  const taken = new Set<string>();
  let view: Box | null = null;
  for (const page of sheets) {
    const shift = shiftOf(page, base);
    const layers = new Set<string>();
    const mine: DrawingItem[] = [];
    for (const src of page.items) {
      if (SHEET_ONLY.has(src.l)) continue;
      // DXF puts dimension lines on layer 0 and labels on A-DIMS: on the drawing it is one layer
      const it = src.l === "0" && src.o?.startsWith("dimension:") ? { ...src, l: "A-DIMS" } : src;
      const box = bbox(it.d);
      if (!inView(page, box)) continue;
      layers.add(it.l);
      if (!taken.has(it.l)) mine.push({ ...it, box: shiftBox(box, shift), shift });
    }
    for (const l of layers) taken.add(l);
    items.push(...mine);
    own.set(page, layers);
    const v = shiftBox(viewOf(page), shift);
    view = view ? [Math.min(view[0], v[0]), Math.min(view[1], v[1]), Math.max(view[2], v[2]), Math.max(view[3], v[3])] : v;
  }
  const objects: Record<string, ObjectCard> = {};
  for (const page of [...sheets].reverse()) Object.assign(objects, page.objects);  // the first sheet wins
  return { base, pages: sheets, items, own, view: view!, objects };
}

// Drawing layers in drawing order and the colour of the first primitive, for the "Layers" panel
export function drawingLayers(d: Drawing): Map<string, string> {
  const out = new Map<string, string>();
  for (const it of d.items) if (!out.has(it.l)) out.set(it.l, it.c);
  return out;
}

// 3D is the wiring sheet scene, shared by all tabs of the drawing
export const sceneOf = (d: Drawing): Scene | null => d.pages.find((p) => p.scene)?.scene ?? null;

// Object layer on the drawing (point:… → E-SOCKET, box:… → W-BOX, wire:… → W-CABLE): 3D hides
// the object together with the tab layer. Labels are not the object's layer
export function objectLayers(d: Drawing): Map<string, string> {
  const out = new Map<string, string>();
  for (const it of d.items) if (it.o && !it.l.endsWith("-TEXT") && !out.has(it.o)) out.set(it.o, it.l);
  return out;
}

// The sheet shows a layer: its own until switched off, one from another sheet if switched on
export const layerShown = (own: Set<string>, hidden: Set<string>, extra: Set<string>, l: string) =>
  (own.has(l) ? !hidden.has(l) : extra.has(l));
