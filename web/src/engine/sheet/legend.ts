// Viewer legend icon: primitives from the sheet (page key legend, sheet mm) → a frame for the
// SVG, so icons of different size (socket, panel, strip) line up in one column

import type { System } from "@/shared/store";
import type { Box, Item, LegendEntry, Page } from "@/shared/types";
import type { Drawing } from "./drawing";
import { bbox } from "./paint";
import { systemOf } from "./views";

export const SYMBOL_PAD = 0.4;  // sheet mm around the icon, for the line width

// Overall bounding box of the primitives with a margin; without primitives, an empty unit frame
export function symbolBox(items: Item[], pad = SYMBOL_PAD): Box {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const it of items) {
    const b = bbox(it.d);
    if (b[0] < x0) x0 = b[0]; if (b[1] < y0) y0 = b[1]; if (b[2] > x1) x1 = b[2]; if (b[3] > y1) y1 = b[3];
  }
  if (x0 === Infinity) return [0, 0, 1, 1];
  return [x0 - pad, y0 - pad, x1 + pad, y1 + pad];
}

// viewBox for <svg>: "x y width height"
export const viewBoxOf = (b: Box) => `${b[0]} ${b[1]} ${b[2] - b[0]} ${b[3] - b[1]}`;

// The legend of the wiring view is the whole drawing: point symbols of the electrical sheet, a
// junction box, the line colour families of the wiring sheet, and the comms line when it has no
// family of its own (a comms point without a group: one colour, not in the sheet legend). The box
// and the comms line take their icon from the drawing itself
export interface WiringLegendTexts { box: string; low: string }

const LINE_W = 8;  // sheet mm: an icon line when the sheet has none to copy the length from

export function wiringLegend(d: Drawing, page: Page, texts: WiringLegendTexts): LegendEntry[] {
  const own = page.legend ?? [];
  const wires = own.filter((e) => e.key.startsWith("wires_"));
  const points = (d.pages.find((p) => p.stage === "electrical")?.legend ?? []).filter((e) => !e.key.startsWith("wires_"));
  const out: LegendEntry[] = [...points];
  const box = d.items.find((it) => it.l === "W-BOX" && it.k === "s");
  if (box) out.push({ key: "box", text: texts.box, items: [{ k: box.k, c: box.c, w: box.w, l: box.l, d: box.d }] });
  out.push(...wires);
  const low = d.items.find((it) => it.l.startsWith("W-CABLE-LOW") && it.k === "s");
  if (low && !wires.some((e) => e.key === "wires_low")) {
    const sample = wires[0] ? symbolBox(wires[0].items, 0) : null;
    const len = sample ? sample[2] - sample[0] : LINE_W;
    out.push({ key: "wires_low", text: texts.low, items: [{ k: "s", c: low.c, w: low.w, l: low.l, d: `M0 0L${len} 0` }] });
  }
  return out;
}

// The system of a legend row: a colour family row has no layer of its own (the sheet draws it on
// W-TEXT), so it follows the lines of its system
const FAMILY_SYSTEM: Record<string, System> = { wires_light: "light", wires_sockets: "sockets", wires_heavy: "sockets", wires_low: "low" };

// A legend row is shown with its objects: a symbol by its layer, a colour family by its system
export function legendShown(e: LegendEntry, own: Set<string>): boolean {
  const sys = FAMILY_SYSTEM[e.key];
  if (sys) return [...own].some((l) => l.startsWith("W-CABLE") && systemOf(l) === sys);
  return e.items.some((i) => own.has(i.l));
}
