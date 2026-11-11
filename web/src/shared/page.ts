// Links between page objects: the whole line (chains), group (groups), cards (objects)

import { label } from "@/shared/i18n";
import type { ObjectCard, Page, XY } from "./types";

// Object keys for matching with tables: a shared label of points means its points
export const expand = (o: string): string[] =>
  (o.startsWith("label:") ? o.slice(6).split(",").map((id) => `point:${id}`) : [o]);

// Point inside rings (outer and holes) by the even-odd rule
export function inRings(rings: XY[][], x: number, y: number): boolean {
  let inside = false;
  for (const ring of rings) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [ax, ay] = ring[i], [bx, by] = ring[j];
      if (ay > y !== by > y && x < ax + ((y - ay) * (bx - ax)) / (by - ay)) inside = !inside;
    }
  }
  return inside;
}

// On the electrics sheets the building is a backdrop: walls, doors, rooms and dimensions are not
// selected there, even on a layer switched on from the plan
const ELECTRIC_STAGES = new Set(["electrical", "lighting", "wiring"]);
const BUILDING = new Set(["room", "zone", "wall", "opening", "dimension"]);
const kindOf = (o: string) => o.slice(0, o.indexOf(":"));

// other holds cards of other sheets of the shared drawing, for objects on a layer switched on
// from another sheet (wires on electrical); the sheet's own cards and lines win
// What a click on a table row selects: its objects with their whole lines; a row already selected
// clears the selection
export function rowSelection(selected: Set<string> | null, keys: string[], chains?: Record<string, string[]>): Set<string> | null {
  if (selected && keys.every((k) => selected.has(k))) return null;
  return new Set(keys.flatMap((k) => [k, ...(chains?.[k] ?? [])]));
}

// A table row is highlighted while the selection holds any of its objects: a route picked on the
// wiring sheet lights the row of its group, which lists all the group's objects (2026-11-11)
export const rowPicked = (selected: Set<string> | null, keys: string[] | undefined): boolean =>
  !!selected && !!keys?.length && keys.some((k) => selected.has(k));

// Objects of the groups not shown (wiring sheet): null filter means none
export function filteredKeys(groups: Record<string, string[]> | undefined, shown: Set<string> | null): Set<string> {
  if (!groups || !shown) return new Set();
  return new Set(Object.entries(groups).filter(([g]) => !shown.has(g)).flatMap(([, keys]) => keys));
}

export class PageIndex {
  readonly objects: Record<string, ObjectCard> | null;
  readonly chains: Record<string, string[]>;
  readonly areas: Record<string, XY[][]>;
  readonly floors: Record<string, XY[][]>;
  readonly groupOf = new Map<string, Set<string>>();
  private readonly electric: boolean;

  // lines are chains of another sheet, for a sheet that shows its lines (sockets view)
  constructor(page: Page, private readonly other: Record<string, ObjectCard> = {}, lines: Record<string, string[]> = {}) {
    this.electric = ELECTRIC_STAGES.has(page.stage || "");
    this.objects = page.objects || null;
    this.chains = page.chains || lines;
    this.areas = page.areas || {};
    this.floors = page.floors || {};
    for (const keys of Object.values(page.groups || {})) {
      const all = new Set(keys);
      for (const k of keys) this.groupOf.set(k, all);
    }
  }

  // An object's line for selection; a label of several points means the lines of all its points
  chainOf(o: string): Set<string> {
    const keys = expand(o).flatMap((k) => this.chains[k] || [k]);
    return new Set([o, ...keys]);
  }

  // Neighbours: the rest of the same QF group (its other boxes, branches and points)
  neighborsOf(chain: Set<string>): Set<string> | null {
    for (const k of chain) {
      const g = this.groupOf.get(k);
      if (g) return g;
    }
    return null;
  }

  interactive(o: string | null | undefined): o is string {
    if (!o || (this.electric && BUILDING.has(kindOf(o)))) return false;
    return !this.objects || o in this.objects || expand(o).some((k) => k in this.chains) || o in this.other;
  }

  // Object by its area on the sheet (walls of the plan): hatching alone is hard to hit
  areaAt(x: number, y: number): string | null {
    const found = Object.entries(this.areas).find(([, rings]) => inRings(rings, x, y));
    return found ? found[0] : null;
  }

  // Floor (a room or a zone of it) under a point of the plan sheet
  floorAt(x: number, y: number): string | null {
    const found = Object.entries(this.floors).find(([, rings]) => inRings(rings, x, y));
    return found ? found[0] : null;
  }

  // Object card; a point on the wiring sheet gets the card of the line to it; otherwise type and id
  card(o: string): ObjectCard {
    const objs = this.objects || {};
    const info = objs[o] || objs[(this.chains[o] || [])[0]] || this.other[o];
    if (info) return info;
    const i = o.indexOf(":");
    return { title: `${label("object", o.slice(0, i))} · ${o.slice(i + 1)}`, rows: [] };
  }
}

// The card of the simple interface mode: a wiring line or box gets its short card (where it runs,
// without group, cable and lengths); a build made before it, only the title
export function briefCard(key: string, card: ObjectCard): ObjectCard {
  if (card.brief) return card.brief;
  return /^(wire|box):/.test(key) ? { title: card.title, rows: [] } : card;
}
