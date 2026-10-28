// Вкладки листов. Листы-продолжения одной темы (развёртки «07 Розгортки», «08 … (продовження)»)
// — одна вкладка, страницы переключаются внутри чертежа (App, «‹ 1 / 3 ›»). Электрика,
// освещение и проводка — одна вкладка «Электрика» с видами: это один чертёж (sheet/drawing.ts),
// вид выбирается справа (SidePanel), а печатные листы остаются отдельными

import type { ManifestPage } from "./types";

// Виды вкладки «Электрика»: тема листа → подпись переключателя
export const VIEWS: Record<string, string> = { electrical: "Точки", lighting: "Освещение", wiring: "Проводка" };

// Имя вкладки — имя листа без номера: «01 План» → «План» (номера — для печати, вкладок меньше,
// чем листов: виды электрики и продолжения развёрток — одна вкладка)
export const tabName = (sheet: string) => sheet.replace(/^\d+\s+/, "");

export interface SheetTab {
  name: string;       // имя первого листа без номера
  pages: number[];    // index листов вкладки по порядку
  views: boolean;     // листы — виды одного чертежа (переключатель справа), а не страницы
}

// Подряд идущие листы с одной темой (stage) — одна вкладка; виды электрики — одна вкладка;
// без темы — каждый сам по себе
export function sheetTabs(pages: readonly ManifestPage[]): SheetTab[] {
  const out: SheetTab[] = [];
  let prev: string | undefined;
  for (const pg of pages) {
    const last = out[out.length - 1];
    const view = !!pg.stage && pg.stage in VIEWS;
    if (last && pg.stage && (view ? last.views : pg.stage === prev && !last.views)) last.pages.push(pg.index);
    else out.push({ name: tabName(pg.name), pages: [pg.index], views: view });
    prev = pg.stage;
  }
  return out;
}

export const tabOf = (tabs: readonly SheetTab[], sheet: number | null) =>
  tabs.find((t) => sheet !== null && t.pages.includes(sheet)) ?? null;
