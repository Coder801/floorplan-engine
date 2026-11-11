// Views of the "Electrical" tab by system: sockets with their lines, lighting, low voltage,
// everything on wiring. Sockets and low voltage are one sheet (electrical) with different layers:
// the printed sheets stay as they are, the view lives only here. Labels and boxes share a layer
// across systems, so they follow their object, not the layer.

import { expand } from "@/shared/page";
import type { ElectricalView } from "@/shared/store";
import type { Page, SideTable } from "@/shared/types";
import type { Drawing } from "./drawing";

const LIGHTING = ["E-LIGHT", "E-SWITCH", "E-LED"];
const HIDES: Record<ElectricalView, string[]> = {
  sockets: [...LIGHTING, "E-DATA"],
  low: [...LIGHTING, "E-SOCKET"],
};
const CABLES: Record<ElectricalView, RegExp> = {
  sockets: /^(W-CABLE-(SOCKET|DEVICE)|W-BOX$|W-TEXT$)/,
  low: /^(W-CABLE-LOW|W-TEXT$)/,
};

// Sheets whose labels and boxes are shown by their object; wiring shows everything
const SCOPED = new Set(["electrical", "lighting"]);
export const scoped = (page: Page) => SCOPED.has(page.stage || "");

// Wiring layers: cables, boxes, their labels (W-…). The simple interface mode (shared/mode.ts)
// shows the points without them: where things are, not how they are wired
const WIRING = /^W-/;

// Layers of the sheet in this view: without the other systems, with the lines of its own
// (without any lines when cables is false)
export function viewLayers(own: Set<string>, all: Iterable<string>, view: ElectricalView, cables = true): Set<string> {
  const out = new Set([...own].filter((l) => !HIDES[view].includes(l) && (cables || !WIRING.test(l))));
  if (cables) for (const l of all) if (CABLES[view].test(l)) out.add(l);
  return out;
}

export function ownLayers(d: Drawing, page: Page, view: ElectricalView, cables = true): Set<string> | null {
  const own = d.own.get(page);
  if (!own) return null;
  if (page.stage !== "electrical") return cables ? own : new Set([...own].filter((l) => !WIRING.test(l)));
  return viewLayers(own, new Set(d.items.map((i) => i.l)), view, cables);
}

// A label or a box is visible with its object: a label with one of its points, a box with one of
// its lines (chains of the wiring sheet). An object not on the drawing stays visible
export function objectVisible(o: string, shown: (layer: string) => boolean, layerOf: Map<string, string>,
                              chains: Record<string, string[]>): boolean {
  const keys = o.startsWith("box:") ? (chains[o] || []).filter((k) => k.startsWith("wire:")) : expand(o);
  const layers = keys.flatMap((k) => layerOf.get(k) ?? []);
  return !layers.length || layers.some(shown);
}

// The lighting sheet numbers its points itself (L-TEXT): the labels of the electrical sheet would
// only repeat them
export const repeatsNumbers = (page: Page, it: { o?: string; l: string }) =>
  page.stage === "lighting" && it.l === "E-TEXT" && !!it.o?.startsWith("label:");

// Primitives that follow their object, not their layer
export const followsObject = (l: string) => l === "W-BOX" || l.endsWith("-TEXT");

// Which view shows an object of the electrical sheet
export function viewOfLayer(layer: string | undefined): ElectricalView | "lighting" {
  if (layer && LIGHTING.includes(layer)) return "lighting";
  return layer === "E-DATA" || layer?.startsWith("W-CABLE-LOW") ? "low" : "sockets";
}

// The sheet tables in this view: rows of the objects it shows; a row without objects stays
export function viewTables(tables: SideTable[], own: Set<string> | null, layerOf: Map<string, string>): SideTable[] {
  if (!own) return tables;
  const hasOwn = (keys: string[]) => {
    const layers = keys.flatMap((k) => expand(k).flatMap((x) => layerOf.get(x) ?? []));
    return !layers.length || layers.some((l) => own.has(l));
  };
  return tables.map((t) => ({ ...t, rows: t.rows.filter((r) => !r.keys || hasOwn(r.keys)) }));
}

// The chains of the wiring sheet: a click on the sockets view selects the whole line too
export const wiringChains = (d: Drawing) => d.pages.find((p) => p.stage === "wiring")?.chains ?? {};
