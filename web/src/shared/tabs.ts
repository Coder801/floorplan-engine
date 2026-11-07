// Sheet tabs. Continuation sheets of one topic (elevations "07 Розгортки", "08 … (продовження)")
// are one tab, with pages switched inside the drawing (Viewer, "‹ 1 / 3 ›"). Electrical,
// lighting and wiring are one "Electrical" tab with views: it is one drawing (sheet/drawing.ts),
// the view is picked on the right (SidePanel), while the printed sheets stay separate

import type { ManifestPage } from "./types";

// A view of the "Electrical" tab: key is its label in i18n views.*; low voltage is a view of the
// electrical sheet, it has no sheet of its own
export interface TabView { key: string; index: number; label: string }

// Views of the "Electrical" tab are sheet topics (labels in i18n views.*)
export const VIEWS = new Set(["electrical", "lighting", "wiring"]);

// Sheet name without the number: "01 План" → "План" (numbers are for print; there are fewer
// tabs than sheets: electrical views and elevation continuations are one tab). A tab with a
// topic is labelled in the interface language (stage.*); this name is the fallback
export const tabName = (sheet: string) => sheet.replace(/^\d+\s+/, "");

export interface SheetTab {
  name: string;       // name of the first sheet without the number (in the project language)
  stage?: string;     // topic: electrical with views is "electrical"
  pages: number[];    // index of the tab's sheets in order
  views: boolean;     // the sheets are views of one drawing (switch on the right), not pages
}

// Consecutive sheets with the same topic (stage) are one tab; electrical views are one tab;
// sheets without a topic stand alone
export function sheetTabs(pages: readonly ManifestPage[]): SheetTab[] {
  const out: SheetTab[] = [];
  let prev: string | undefined;
  for (const pg of pages) {
    const last = out[out.length - 1];
    const view = !!pg.stage && VIEWS.has(pg.stage);
    if (last && pg.stage && (view ? last.views : pg.stage === prev && !last.views)) last.pages.push(pg.index);
    else out.push({ name: tabName(pg.name), stage: view ? "electrical" : pg.stage, pages: [pg.index], views: view });
    prev = pg.stage;
  }
  return out;
}

export const tabOf = (tabs: readonly SheetTab[], sheet: number | null) =>
  tabs.find((t) => sheet !== null && t.pages.includes(sheet)) ?? null;
