// Drawing .epd primitives into a canvas by the format rules (docs/epd-format.md)

import { MIN_LINE_PX, PNG_DPI, PNG_LONG, PNG_SHORT } from "@/shared/consts";
import type { Box, Item, Page } from "@/shared/types";

export interface DrawItem extends Item {
  box: Box;
  path: Path2D;
}

// [colour, opacity, how much thicker, the path moved elsewhere (a socket of an opening stack)]
export type Look = (it: DrawItem) => [string, number, number, Path2D?];

// The screen shows only the drawing: the sheet viewport (view); old artifacts show the whole sheet
export const viewOf = (page: Page): Box => page.view || [0, 0, page.size[0], page.size[1]];

export function inView(page: Page, box: Box): boolean {
  if (!page.view) return true;
  const [x0, y0, x1, y1] = page.view;
  return box[2] >= x0 && box[0] <= x1 && box[3] >= y0 && box[1] <= y1;
}

// Layers the screen draws bolder (bold in paint): everything but the building (walls, openings,
// dimensions, sheet frame)
const boldLayer = (l: string) => !l.startsWith("A-") && l !== "0";

// Primitives in order; pxPerMm is for the minimum line width; cableMinPx keeps wiring lines on
// screen at least this thick (device px); 0 in PNG. bold thickens the engineering lines on
// screen (SCREEN_BOLD); 1 in PNG, the printed sheet stays as built
export function paint(ctx: CanvasRenderingContext2D, items: DrawItem[], pxPerMm: number, look: Look,
                      shown: (layer: string) => boolean, cableMinPx = 0, bold = 1) {
  ctx.lineCap = "round"; ctx.lineJoin = "round";
  const minW = MIN_LINE_PX / pxPerMm, cableW = Math.max(cableMinPx / pxPerMm, minW);
  for (const it of items) {
    if (!shown(it.l)) continue;
    const [c, alpha, k, path] = look(it);
    ctx.globalAlpha = alpha;
    if (!alpha) continue;
    if (it.k === "f") { ctx.fillStyle = c; ctx.fill(path ?? it.path, "nonzero"); }
    else {
      ctx.strokeStyle = c;
      ctx.lineWidth = Math.max(it.w || 0, it.l.startsWith("W-CABLE") ? cableW : minW) * k * (boldLayer(it.l) ? bold : 1);
      ctx.stroke(path ?? it.path);
    }
  }
  ctx.globalAlpha = 1;
}

// Path bounds: d holds only absolute commands, numbers come in x y pairs
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

// Sheet PNG for the album: the whole sheet with tables and title block, at most A3 at 150 dpi
export function downloadSheetPng(page: Page, filename: string) {
  const [pw, ph] = page.size;
  const k = Math.min(PNG_DPI / 25.4, PNG_LONG / Math.max(pw, ph), PNG_SHORT / Math.min(pw, ph));
  const out = document.createElement("canvas");
  out.width = Math.round(pw * k); out.height = Math.round(ph * k);
  const ctx = out.getContext("2d")!;
  ctx.setTransform(k, 0, 0, k, 0, 0);
  ctx.fillStyle = page.background || "#ffffff";
  ctx.fillRect(0, 0, pw, ph);
  const all = page.items.map((i) => ({ ...i, box: [0, 0, 0, 0] as DrawItem["box"], path: new Path2D(i.d) }));
  paint(ctx, all, k, (it) => [it.c, 1, 1], () => true);
  out.toBlob((blob) => {
    if (!blob) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = filename;
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }, "image/png");
}
