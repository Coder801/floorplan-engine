// Значок легенды просмотра: примитивы с листа (ключ legend страницы, мм листа) → рамка
// для SVG, чтобы значки разной величины (розетка, щит, лента) стояли в одной колонке

import type { Box, Item } from "@/shared/types";
import { bbox } from "./paint";

export const SYMBOL_PAD = 0.4;  // мм листа вокруг значка — под толщину линии

// Общий габарит примитивов с полем; без примитивов — пустая рамка единичного размера
export function symbolBox(items: Item[], pad = SYMBOL_PAD): Box {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const it of items) {
    const b = bbox(it.d);
    if (b[0] < x0) x0 = b[0]; if (b[1] < y0) y0 = b[1]; if (b[2] > x1) x1 = b[2]; if (b[3] > y1) y1 = b[3];
  }
  if (x0 === Infinity) return [0, 0, 1, 1];
  return [x0 - pad, y0 - pad, x1 + pad, y1 + pad];
}

// viewBox для <svg>: «x y width height»
export const viewBoxOf = (b: Box) => `${b[0]} ${b[1]} ${b[2] - b[0]} ${b[3] - b[1]}`;
