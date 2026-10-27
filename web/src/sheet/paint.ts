// Рисование примитивов .epd в canvas по правилам формата (docs/epd-format.md)

import { MIN_LINE_PX } from "../consts";
import type { Box, Item, Page } from "../types";

export interface DrawItem extends Item {
  box: Box;
  path: Path2D;
}

// [цвет, прозрачность, во сколько толще]
export type Look = (it: DrawItem) => [string, number, number];

// На экране — только чертёж: видовой экран листа (view); старые артефакты — целым листом
export const viewOf = (page: Page): Box => page.view || [0, 0, page.size[0], page.size[1]];

export function inView(page: Page, box: Box): boolean {
  if (!page.view) return true;
  const [x0, y0, x1, y1] = page.view;
  return box[2] >= x0 && box[0] <= x1 && box[3] >= y0 && box[1] <= y1;
}

// Примитивы по порядку; pxPerMm — для минимальной толщины линии; cableMinPx — на экране
// линии проводки не тоньше этого (px устройства); в PNG — 0
export function paint(ctx: CanvasRenderingContext2D, items: DrawItem[], pxPerMm: number, look: Look,
                      hidden: Set<string>, cableMinPx = 0) {
  ctx.lineCap = "round"; ctx.lineJoin = "round";
  const minW = MIN_LINE_PX / pxPerMm, cableW = Math.max(cableMinPx / pxPerMm, minW);
  for (const it of items) {
    if (hidden.has(it.l)) continue;
    const [c, alpha, k] = look(it);
    ctx.globalAlpha = alpha;
    if (it.k === "f") { ctx.fillStyle = c; ctx.fill(it.path, "nonzero"); }
    else {
      ctx.strokeStyle = c;
      ctx.lineWidth = Math.max(it.w || 0, it.l.startsWith("W-CABLE") ? cableW : minW) * k;
      ctx.stroke(it.path);
    }
  }
  ctx.globalAlpha = 1;
}

// Габариты пути: в d только абсолютные команды, числа идут парами x y
export function bbox(d: string): Box {
  const nums = d.match(/-?\d*\.?\d+(?:e-?\d+)?/gi) || [];
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let i = 0; i + 1 < nums.length; i += 2) {
    const x = +nums[i], y = +nums[i + 1];
    if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
  }
  return [x0, y0, x1, y1];
}

export const inBox = (b: Box, x: number, y: number, t: number) =>
  x >= b[0] - t && x <= b[2] + t && y >= b[1] - t && y <= b[3] + t;
