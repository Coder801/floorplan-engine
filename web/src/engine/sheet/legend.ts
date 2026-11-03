// Viewer legend icon: primitives from the sheet (page key legend, sheet mm) → a frame for the
// SVG, so icons of different size (socket, panel, strip) line up in one column

import type { Box, Item } from "@/shared/types";
import { bbox } from "./paint";

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
