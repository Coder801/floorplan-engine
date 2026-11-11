// Sheet tabs. Continuation sheets of one topic (elevations "07 Розгортки", "08 … (продовження)")
// are one tab, with pages switched inside the drawing (Viewer, "‹ 1 / 3 ›"). Electrical,
// lighting and wiring are one "Electrical" tab with views: it is one drawing (sheet/drawing.ts),
// the view is picked on the right (SidePanel), while the printed sheets stay separate.
// The views are systems: lighting, sockets, low voltage, and wiring with everything. Lighting,
// sockets and low voltage are layers of the electrical sheet (engine/sheet/views.ts); lighting
// also has its links, the lighting sheet ("Wiring | Links" over the drawing, SheetStage)

import type { ElectricalView } from "./store";
import type { ManifestPage } from "./types";

// A view of the "Electrical" tab: key is its label in i18n views.*
export interface TabView { key: string; index: number; label: string }

// Views in tab order; "electrical" is sockets (the key stays the sheet topic)
export const VIEW_KEYS = ["lighting", "electrical", "low", "wiring"] as const;

// What the electrical sheet shows in a view; wiring and the lighting links are sheets of their own
export const ELECTRICAL_VIEW: Readonly<Record<string, ElectricalView>> = { lighting: "light", electrical: "sockets", low: "low" };

type StageOf = (i: number) => string | undefined;

// The sheet of a view in a tab. Lighting is its lines (electrical sheet) or, with links, its
// links (lighting sheet); either one when the other sheet is missing
export function viewSheet(tb: SheetTab, stageOf: StageOf, key: string, links: boolean): number | undefined {
  const at = (st: string) => tb.pages.find((i) => stageOf(i) === st);
  if (key === "lighting") return links ? at("lighting") ?? at("electrical") : at("electrical") ?? at("lighting");
  return at(key === "wiring" ? "wiring" : "electrical");
}

// Views of a tab with their sheets; low voltage only if the project has it
export function tabViews(tb: SheetTab, stageOf: StageOf, hasLow: boolean, links: boolean): { key: string; index: number }[] {
  return VIEW_KEYS.filter((k) => k !== "low" || hasLow).flatMap((key) => {
    const index = viewSheet(tb, stageOf, key, links);
    return index === undefined ? [] : [{ key, index }];
  });
}

// The view shown: by the sheet, and on the electrical sheet by what it shows
export function shownView(stage: string, view: ElectricalView): string {
  if (stage !== "electrical") return stage;
  return view === "light" ? "lighting" : view === "low" ? "low" : "electrical";
}

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
