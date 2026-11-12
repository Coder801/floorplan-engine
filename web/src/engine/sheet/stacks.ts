// Symbols on screen: a little larger than on the printed sheet (SYMBOL_GROW), and a stack of
// sockets (or of switches) at one place of a wall as one symbol. The sheet draws such a stack
// from the wall into the room, one symbol after another, with one shared label past the last one
// (drawing/electrical.py, label_clusters). The screen shows only the symbol nearest the wall and
// a count; on hover, selection or a lit table row the stack opens: the symbols slide out to
// their places (SheetView). Sockets and switches of one place are two stacks under one label,
// they open together. Pure functions: the paths are moved by SheetView.

import { expand } from "@/shared/page";
import type { Box } from "@/shared/types";

type XY = [number, number];

interface Placed { o?: string; l: string; box: Box }

// Point and box symbols: what grows on screen. The panel keeps its true width
const SYMBOL_LAYERS = new Set(["E-SOCKET", "E-SWITCH", "E-LIGHT", "E-LED", "E-DATA", "W-BOX"]);
const SYMBOL_KINDS = /^(point|box):/;
export const isSymbol = (it: { o?: string; l: string }) =>
  !!it.o && SYMBOL_LAYERS.has(it.l) && SYMBOL_KINDS.test(it.o);

export const centerOf = (b: Box): XY => [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];

const union = (a: Box | undefined, b: Box): Box =>
  (a ? [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])] : [...b]);

// Box of each object over its primitives that pass the filter
function boxesOf(items: readonly Placed[], keep: (it: Placed) => boolean): Map<string, Box> {
  const out = new Map<string, Box>();
  for (const it of items) if (it.o && keep(it)) out.set(it.o, union(out.get(it.o), it.box));
  return out;
}

// Centre of each symbol: it grows about it, so a symbol stays where it stands
export const symbolCenters = (items: readonly Placed[]): Map<string, XY> =>
  new Map([...boxesOf(items, isSymbol)].map(([o, b]) => [o, centerOf(b)]));

// A box grown f times about c
export const grownBox = ([x0, y0, x1, y1]: Box, [cx, cy]: XY, f: number): Box =>
  [cx + (x0 - cx) * f, cy + (y0 - cy) * f, cx + (x1 - cx) * f, cy + (y1 - cy) * f];

// Layers whose symbols close into stacks
export const STACK_LAYERS = ["E-SOCKET", "E-SWITCH"] as const;

export interface Stack {
  key: string;                  // the stack: label and layer (label:a,b,c|E-SOCKET)
  label: string;                // the shared label (label:a,b,c): one per place of a wall
  layer: string;                // what it stacks: sockets or switches
  anchor: string;               // the symbol nearest the wall: shown while the stack is closed
  count: XY;                    // where the count stands: the corner of the anchor on the room side
  rest: string[];               // the sockets after it, from the wall into the room
  shift: Record<string, XY>;    // from a socket of rest to the anchor: where it hides
  box: Box;                     // all its sockets: the pointer inside keeps the stack open
}

// Stacks of the sheet, sockets and switches apart. The label stands past the symbol farthest
// from the wall, so the symbol at the wall is the one farthest from the label; the stack is the
// symbols of the layer on the line from it to the label. Symbols side by side along the wall
// stay apart: they are other places
export function pointStacks(items: readonly Placed[], layers: readonly string[] = STACK_LAYERS): Stack[] {
  return layers.flatMap((layer) => layerStacks(items, layer));
}

function layerStacks(items: readonly Placed[], layer: string): Stack[] {
  const sockets = boxesOf(items, (it) => it.l === layer && !!it.o?.startsWith("point:"));
  const labels = boxesOf(items, (it) => !!it.o?.startsWith("label:") && it.o.includes(","));
  const out: Stack[] = [];
  for (const [label, labelBox] of labels) {
    const members = expand(label).filter((k) => sockets.has(k));
    if (members.length < 2) continue;
    const [lx, ly] = centerOf(labelBox);
    const at = (k: string) => centerOf(sockets.get(k)!);
    const far = (k: string) => Math.hypot(at(k)[0] - lx, at(k)[1] - ly);
    const anchor = members.reduce((a, b) => (far(b) > far(a) + 1e-6 ? b : a));
    const [ax, ay] = at(anchor), len = far(anchor);
    if (len < 1e-6) continue;
    const ux = (lx - ax) / len, uy = (ly - ay) / len;
    const ab = sockets.get(anchor)!;
    const tol = Math.min(ab[2] - ab[0], ab[3] - ab[1]) / 2;
    // On the axis from the wall to the label, ordered from the wall
    const rest = members
      .filter((k) => k !== anchor && Math.abs((at(k)[0] - ax) * uy - (at(k)[1] - ay) * ux) <= tol)
      .sort((a, b) => ((at(a)[0] - ax) * ux + (at(a)[1] - ay) * uy) - ((at(b)[0] - ax) * ux + (at(b)[1] - ay) * uy));
    if (!rest.length) continue;
    const shift: Record<string, XY> = {};
    let box = ab;
    for (const k of rest) {
      shift[k] = [ax - at(k)[0], ay - at(k)[1]];
      box = union(box, sockets.get(k)!);
    }
    // The corner towards the room (the stack goes there); along the wall, the upper or left one
    const count: XY = [ux < -0.3 ? ab[0] : ab[2], uy > 0.3 ? ab[3] : ab[1]];
    out.push({ key: `${label}|${layer}`, label, layer, anchor, count, rest, shift, box });
  }
  return out;
}

// Stack keys to open: the pointer holds a place (its label), or a symbol of the place (or its
// label) is under the cursor, selected or lit by a table row; the stacks of one place open together
export function openStacks(stacks: readonly Stack[], held: string | null,
                           marked: readonly (ReadonlySet<string> | string | null | undefined)[]): Set<string> {
  const has = (k: string) => marked.some((m) => (typeof m === "string" ? m === k : !!m?.has(k)));
  const hit = (s: Stack) => has(s.label) || has(s.anchor) || s.rest.some(has);
  const places = new Set(stacks.filter((s) => s.label === held || hit(s)).map((s) => s.label));
  return new Set(stacks.filter((s) => places.has(s.label)).map((s) => s.key));
}
