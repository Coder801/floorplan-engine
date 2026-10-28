// Один чертёж на листы с планом (план, электрика, освещение, проводка): примитивы всех листов
// в координатах одного листа (base, первый по порядку) — по их model. Слой берётся с первого
// листа, где он есть в видовом экране: стены и размеры — с плана, точки — с электрики, связи —
// с освещения, кабели — с проводки; те же слои на других листах — копии и не повторяются.
// Вкладка листа — набор его слоёв (own): переключение вкладки меняет слои, а не чертёж,
// масштаб и сдвиг остаются. Слои с других листов включаются в «Слоях» (store.extra).

import { SHEET_ONLY } from "../consts";
import type { Box, Item, ObjectCard, Page, Scene } from "../types";
import { bbox, inView, viewOf } from "./paint";

// Листы одного чертежа; щит, развёртки и ведомость — сами по себе
export const DRAWING_STAGES = new Set(["plan", "electrical", "lighting", "wiring"]);

// С листа-источника на base: x' = f·x + dx, y' = f·y + dy (мм листа)
export interface Shift { f: number; dx: number; dy: number }

export const IDENTITY: Shift = { f: 1, dx: 0, dy: 0 };

export interface DrawingItem extends Item {
  box: Box;       // габарит уже на base
  shift: Shift;   // путь d — ещё в мм своего листа
}

export interface Drawing {
  base: Page;
  pages: Page[];
  items: DrawingItem[];
  own: Map<Page, Set<string>>;     // слои, которые лист показывает сам
  view: Box;                       // видовые экраны всех листов на base
  objects: Record<string, ObjectCard>;  // карточки всех листов — для слоёв с чужого листа
}

// x листа = k·x + tx, y листа = ty − k·y (docs/epd-format.md, model): модель общая,
// поэтому лист → лист — масштаб и сдвиг
export function shiftOf(from: Page, to: Page): Shift {
  if (from === to || !from.model || !to.model) return IDENTITY;
  const [ks, txs, tys] = from.model, [kb, txb, tyb] = to.model;
  const f = kb / ks;
  return { f, dx: txb - f * txs, dy: tyb - f * tys };
}

export const shiftBox = ([x0, y0, x1, y1]: Box, { f, dx, dy }: Shift): Box =>
  [f * x0 + dx, f * y0 + dy, f * x1 + dx, f * y1 + dy];

// Листы без model (щит, развёртки) в общий чертёж не складываются — чертёж из одного листа
export function buildDrawing(pages: Page[]): Drawing {
  const sheets = pages.length > 1 && pages.every((p) => p.model) ? pages : pages.slice(0, 1);
  const base = sheets[0];
  const items: DrawingItem[] = [];
  const own = new Map<Page, Set<string>>();
  const taken = new Set<string>();
  let view: Box | null = null;
  for (const page of sheets) {
    const shift = shiftOf(page, base);
    const layers = new Set<string>();
    const mine: DrawingItem[] = [];
    for (const src of page.items) {
      if (SHEET_ONLY.has(src.l)) continue;
      // Линии размеров DXF кладёт в слой 0, подписи — в A-DIMS: на чертеже это один слой
      const it = src.l === "0" && src.o?.startsWith("dimension:") ? { ...src, l: "A-DIMS" } : src;
      const box = bbox(it.d);
      if (!inView(page, box)) continue;
      layers.add(it.l);
      if (!taken.has(it.l)) mine.push({ ...it, box: shiftBox(box, shift), shift });
    }
    for (const l of layers) taken.add(l);
    items.push(...mine);
    own.set(page, layers);
    const v = shiftBox(viewOf(page), shift);
    view = view ? [Math.min(view[0], v[0]), Math.min(view[1], v[1]), Math.max(view[2], v[2]), Math.max(view[3], v[3])] : v;
  }
  const objects: Record<string, ObjectCard> = {};
  for (const page of [...sheets].reverse()) Object.assign(objects, page.objects);  // первый лист главнее
  return { base, pages: sheets, items, own, view: view!, objects };
}

// Слои чертежа в порядке рисования и цвет первого примитива — для панели «Слои»
export function drawingLayers(d: Drawing): Map<string, string> {
  const out = new Map<string, string>();
  for (const it of d.items) if (!out.has(it.l)) out.set(it.l, it.c);
  return out;
}

// 3D — сцена листа проводки, общая для всех вкладок чертежа
export const sceneOf = (d: Drawing): Scene | null => d.pages.find((p) => p.scene)?.scene ?? null;

// Слой объекта на чертеже (point:… → E-SOCKET, box:… → W-BOX, wire:… → W-CABLE): 3D прячет
// объект вместе со слоем вкладки. Подписи — не слой объекта
export function objectLayers(d: Drawing): Map<string, string> {
  const out = new Map<string, string>();
  for (const it of d.items) if (it.o && !it.l.endsWith("-TEXT") && !out.has(it.o)) out.set(it.o, it.l);
  return out;
}

// Лист показывает слой: свой — пока не выключен, с другого листа — если включён
export const layerShown = (own: Set<string>, hidden: Set<string>, extra: Set<string>, l: string) =>
  (own.has(l) ? !hidden.has(l) : extra.has(l));
