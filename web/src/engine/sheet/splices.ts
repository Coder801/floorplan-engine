// Joint marks of the wiring sheet (decision 2026-11-25): a point whose flush box joins wires
// (looped sockets, lights in a chain; key splice of its card) gets a small dot on the top right
// corner of its symbol — the joint dot of a circuit diagram. SheetView draws it on screen, the
// legend shows the same dot on the symbol. Pure functions; the printed sheet has no mark

import type { Box, Item, Page } from "@/shared/types";
import { bbox } from "./paint";
import { isSymbol } from "./stacks";

type XY = [number, number];

interface Placed { o?: string; l: string; k: "s" | "f"; box: Box }

// Points of the page with a joint in their flush box: only the wiring sheet marks them
export function splicePoints(page: Page): Set<string> {
  if (page.stage !== "wiring" || !page.objects) return new Set();
  return new Set(Object.entries(page.objects).filter(([k, v]) => k.startsWith("point:") && v.splice).map(([k]) => k));
}

export interface SpliceMark<T> {
  key: string;
  at: XY;       // the top right corner of the symbol
  size: number; // the larger side of the symbol, for the dot radius
  item: T;      // a line of the symbol (not its white inside): the layer, colour and highlight
}

// Mark of each point of keys over its symbol primitives (as placed on screen: grown about the centre)
export function spliceMarks<T extends Placed>(items: readonly T[], keys: ReadonlySet<string>): SpliceMark<T>[] {
  const boxes = new Map<string, { box: Box; item: T }>();
  for (const it of items) {
    if (!it.o || !keys.has(it.o) || !isSymbol(it)) continue;
    const b = boxes.get(it.o);
    boxes.set(it.o, b
      ? { item: b.item.k === "s" ? b.item : it, box: [Math.min(b.box[0], it.box[0]), Math.min(b.box[1], it.box[1]), Math.max(b.box[2], it.box[2]), Math.max(b.box[3], it.box[3])] }
      : { item: it, box: [...it.box] });
  }
  return [...boxes].map(([key, { box, item }]) => ({
    key, at: [box[2], box[1]], size: Math.max(box[2] - box[0], box[3] - box[1]), item,
  }));
}

export const MARK_SHARE = 0.16;  // dot radius to the symbol size
export const MARK_MIN_PX = 2.5;  // and never smaller on screen

// The dot as a path of the format (a polygon: bbox reads only points), sheet mm
export function dotPath([cx, cy]: XY, r: number, n = 16): string {
  const pts = Array.from({ length: n }, (_, i) => {
    const a = (2 * Math.PI * i) / n;
    return `${+(cx + r * Math.cos(a)).toFixed(2)} ${+(cy + r * Math.sin(a)).toFixed(2)}`;
  });
  return `M${pts.join("L")}Z`;
}

// Legend icon: the symbol of a marked point with its dot, from the sheet primitives (their own
// sheet mm, as the legend draws them)
export function spliceIcon(items: readonly Item[], key: string): Item[] {
  const own = items.filter((it) => it.o === key && isSymbol(it)).map((it) => ({ ...it, box: bbox(it.d) }));
  const [mark] = spliceMarks(own, new Set([key]));
  if (!mark) return [];
  const symbol = own.map((it) => ({ k: it.k, c: it.c, w: it.w, l: it.l, d: it.d }));
  // A little larger than on screen: the icon is drawn small
  return [...symbol, { k: "f", c: mark.item.c, l: mark.item.l, d: dotPath(mark.at, mark.size * MARK_SHARE * 1.4) }];
}
