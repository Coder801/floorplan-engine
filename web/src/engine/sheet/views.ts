// Views of the "Electrical" tab by system: lighting, sockets, low voltage, each with its own
// lines and boxes, and wiring with everything. Lighting, sockets and low voltage are one sheet
// (electrical) with different layers; lighting also has its links view (the lighting sheet).
// The printed sheets stay as they are, the views live only here. Labels and boxes share a
// layer across systems, so they follow their object, not the layer.

import { expand } from "@/shared/page";
import type { ElectricalView, System } from "@/shared/store";
import type { Page, SideTable } from "@/shared/types";
import type { Drawing } from "./drawing";

const LIGHTING = ["E-LIGHT", "E-SWITCH", "E-LED"];
const HIDES: Record<ElectricalView, string[]> = {
  sockets: [...LIGHTING, "E-DATA"],
  low: [...LIGHTING, "E-SOCKET"],
  light: ["E-SOCKET", "E-DATA"],
};
const CABLES: Record<ElectricalView, RegExp> = {
  sockets: /^(W-CABLE-(SOCKET|DEVICE)|W-BOX$|W-TEXT$)/,
  low: /^(W-CABLE-LOW|W-TEXT$)/,
  light: /^(W-CABLE-LIGHT|W-BOX$|W-TEXT$)/,
};

// The system of a layer: its points, links and lines; walls, the panel, boxes and labels have none
export function systemOf(l: string): System | null {
  if (LIGHTING.includes(l) || l === "E-LINK" || l.startsWith("W-CABLE-LIGHT")) return "light";
  if (l === "E-SOCKET" || l.startsWith("W-CABLE-SOCKET") || l.startsWith("W-CABLE-DEVICE")) return "sockets";
  if (l === "E-DATA" || l.startsWith("W-CABLE-LOW")) return "low";
  return null;
}

// Sheets whose labels and boxes are shown by their object; on wiring that matters once a system is off
const SCOPED = new Set(["electrical", "lighting", "wiring"]);
export const scoped = (page: Page) => SCOPED.has(page.stage || "");

// Wiring layers: cables, boxes, their labels (W-…). The simple interface mode (shared/mode.ts)
// shows the points without them: where things are, not how they are wired. The wiring sheet
// itself keeps the lines and boxes there, without labels (cable marks, box numbers)
const WIRING = /^W-/;
const WIRING_LABELS = "W-TEXT";

// Layers of the sheet in this view: without the other systems, with the lines of its own
// (without any lines when cables is false)
export function viewLayers(own: Set<string>, all: Iterable<string>, view: ElectricalView, cables = true): Set<string> {
  const out = new Set([...own].filter((l) => !HIDES[view].includes(l) && (cables || !WIRING.test(l))));
  if (cables) for (const l of all) if (CABLES[view].test(l)) out.add(l);
  return out;
}

// Layers of a sheet of the drawing; the wiring sheet without the systems switched off
export function ownLayers(d: Drawing, page: Page, view: ElectricalView, cables = true,
                          off: ReadonlySet<System> = new Set()): Set<string> | null {
  const own = d.own.get(page);
  if (!own) return null;
  if (page.stage === "electrical") return viewLayers(own, new Set(d.items.map((i) => i.l)), view, cables);
  const wiring = page.stage === "wiring";
  if (cables && !(wiring && off.size)) return own;
  const hides = (l: string) => {
    const sys = systemOf(l);
    if (wiring && sys && off.has(sys)) return true;
    if (cables) return false;
    return wiring ? l === WIRING_LABELS : WIRING.test(l);
  };
  return new Set([...own].filter((l) => !hides(l)));
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

// Which view of the electrical sheet shows an object
export function viewOfLayer(layer: string | undefined): ElectricalView {
  const sys = layer ? systemOf(layer) : null;
  return sys === "light" || sys === "low" ? sys : "sockets";
}

// The sheet tables in this view: rows of the objects it shows; a row without objects stays.
// Objects of a system decide: a group row of a switched-off system goes, though its boxes stay
export function viewTables(tables: SideTable[], own: Set<string> | null, layerOf: Map<string, string>): SideTable[] {
  if (!own) return tables;
  const hasOwn = (keys: string[]) => {
    const layers = keys.flatMap((k) => expand(k).flatMap((x) => layerOf.get(x) ?? []));
    const ofSystem = layers.filter((l) => systemOf(l));
    const decide = ofSystem.length ? ofSystem : layers;
    return !decide.length || decide.some((l) => own.has(l));
  };
  return tables.map((t) => ({ ...t, rows: t.rows.filter((r) => !r.keys || hasOwn(r.keys)) }));
}

// The chains of the wiring sheet: a click on the sockets view selects the whole line too
export const wiringChains = (d: Drawing) => d.pages.find((p) => p.stage === "wiring")?.chains ?? {};

// Light links of the lighting sheet (E-LINK) have no cards: a switch link knows its switch, a
// light set its lights. A selection lights a link through its points and dims the rest
export function linkEnds(o: string | undefined): string[] | null {
  if (!o) return null;
  if (o.startsWith("switch_link:")) return [`point:${o.slice(12)}`];
  if (o.startsWith("light_set:")) return o.slice(10).split(",").map((id) => `point:${id}`);
  return null;
}
