// A wall thumbnail for the "All walls" overview: the elevation's own sheet primitives (the ones
// tagged with its object, as on the printed sheet), fitted into a fixed card

import { paint, type DrawItem } from "@/engine/sheet/paint";
import type { WallPage } from "@/engine/sheet/walls";
import { screenColor } from "@/shared/palette";
import type { Box, Page } from "@/shared/types";

export const THUMB_W = 240;  // card picture, CSS px (16:10)
export const THUMB_H = 150;
const PAD_PX = 10;

// Scale and offset that fit a box (sheet mm) into w × h px with a margin, centred
export function fitBox([x0, y0, x1, y1]: Box, w: number, h: number, pad = PAD_PX): { k: number; ox: number; oy: number } {
  const bw = Math.max(x1 - x0, 1e-6), bh = Math.max(y1 - y0, 1e-6);
  const k = Math.max(Math.min((w - 2 * pad) / bw, (h - 2 * pad) / bh), 0);
  return { k, ox: (w - bw * k) / 2 - x0 * k, oy: (h - bh * k) / 2 - y0 * k };
}

// Draw the wall into the canvas in screen colours (the theme), at the device pixel ratio
export function drawThumb(canvas: HTMLCanvasElement, page: Page, wall: WallPage, dpr: number) {
  canvas.width = Math.round(THUMB_W * dpr); canvas.height = Math.round(THUMB_H * dpr);
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const { k, ox, oy } = fitBox(wall.box, THUMB_W, THUMB_H);
  ctx.setTransform(k * dpr, 0, 0, k * dpr, ox * dpr, oy * dpr);
  const items: DrawItem[] = page.items.filter((it) => it.o === wall.key)
    .map((it) => ({ ...it, box: [0, 0, 0, 0], path: new Path2D(it.d) }));
  paint(ctx, items, k * dpr, (it) => [screenColor(it.c), 1, 1], () => true);
}
