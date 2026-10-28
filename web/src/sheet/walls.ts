// Развёртки постранично: одна страница просмотра — одна стена. На печатном листе развёрток
// много (sheets.elevations_spec), но каждая помечена своим объектом elevation:<комната>.<стена>
// (ids.tagged) — по нему находится её габарит, и чертёж показывает только его.

import type { Box, Page } from "../types";
import { bbox } from "./paint";

const PAD_MM = 4;  // поле вокруг развёртки, мм листа

export interface WallPage {
  sheet: number;   // лист, на котором развёртка
  key: string;     // elevation:bath.w3
  box: Box;        // габарит на листе, с полем
  title: string;   // «Санвузол — стіна 3» (карточка объекта) или ключ
}

// Развёртки листов по порядку: листы — как переданы, на листе — по первому примитиву
export function wallPages(sheets: readonly { index: number; page: Page }[]): WallPage[] {
  const out: WallPage[] = [];
  for (const { index, page } of sheets) {
    const boxes = new Map<string, Box>();
    for (const it of page.items) {
      if (!it.o || !it.o.startsWith("elevation:")) continue;
      const [x0, y0, x1, y1] = bbox(it.d);
      const b = boxes.get(it.o);
      boxes.set(it.o, b ? [Math.min(b[0], x0), Math.min(b[1], y0), Math.max(b[2], x1), Math.max(b[3], y1)]
        : [x0, y0, x1, y1]);
    }
    for (const [key, [x0, y0, x1, y1]] of boxes) {
      out.push({
        sheet: index, key, box: [x0 - PAD_MM, y0 - PAD_MM, x1 + PAD_MM, y1 + PAD_MM],
        title: page.objects?.[key]?.title ?? key.slice("elevation:".length),
      });
    }
  }
  return out;
}

// Слева от развёртки — поле под мини-схему квартиры (WallMap внизу слева): доля ширины
// развёртки, но не меньше доли высоты — у узкой высокой стены ширина мала
export const MAP_ROOM = 0.32;

// Лист одной развёртки: только её примитивы (в поле слева — соседняя развёртка листа),
// видовой экран — её габарит с полем под мини-схему. PNG для альбома — с исходного листа
export function wallSheet(page: Page, w: WallPage): Page {
  const [x0, y0, x1, y1] = w.box;
  const room = MAP_ROOM * Math.max(x1 - x0, y1 - y0);
  return { ...page, items: page.items.filter((it) => it.o === w.key), view: [x0 - room, y0, x1, y1] };
}
