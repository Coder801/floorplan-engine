// Sections of the header: the first menu level. A domain (electrical, plumbing, later walls and
// so on) gathers its sheet tabs (shared/tabs.ts) into one section, its sheets are the second
// level under the header. A tab outside every domain (plan, furniture) is a section of its own.
// Each domain has its own elevations (decision 2026-11-18): its own tab with only its walls; the
// wall engine is one, the tab picks the layers seen on the wall (WALL_LAYERS).
// A domain is a service of the project (decision 2026-11-23): the admin ticks the services, the
// viewer drops the sheets, wall layers and overview blocks of those switched off (servicePages…).

import type { WallLayers } from "./store";
import { VIEWS, type SheetTab } from "./tabs";
import type { ManifestPage, Overview } from "./types";

// Domains in menu order; stages are tab topics (SheetTab.stage). A new domain is a row here
export const DOMAINS: readonly { key: string; stages: readonly string[] }[] = [
  { key: "electrical", stages: ["electrical", "panel", "floor_heating", "elevations"] },
  { key: "plumbing", stages: ["plumbing", "plumbing_elevations"] },
];

// Tabs of a domain that stand among the views of the "Electrical" tab in the second menu row:
// before the named view (floor heating — after "Low voltage", before "Wiring"). The printed
// sheets keep their order; only the menu changes
export const BEFORE_VIEW: Readonly<Record<string, string>> = { floor_heating: "wiring" };

// A second-row item: a view of the "Electrical" tab (view) or a sheet tab (stage)
export interface SubItemPlace { view?: string; stage?: string }

// Sheets of a domain held back until the next release (decision 2026-11-22): the menu keeps them
// greyed out and inert, with a hint, whether or not the build has the sheet (an old build may)
export const COMING_SOON: Readonly<Record<string, readonly string[]>> = { electrical: ["floor_heating"] };

// A sheet topic held back until the next release (in any domain)
export const heldBack = (stage: string | undefined): boolean =>
  Object.values(COMING_SOON).some((stages) => stages.includes(stage ?? ""));

// The second-row items of a domain with its held-back sheets: a built one is replaced, a missing
// one is added; `soon` makes the item of a stage (placed by placeAmongViews like any other)
export function withComingSoon<T extends SubItemPlace>(items: readonly T[], domain: string, soon: (stage: string) => T): T[] {
  const held = COMING_SOON[domain] ?? [];
  return [...items.filter((it) => !held.includes(it.stage ?? "")), ...held.map(soon)];
}

// Second-row items with the tabs of BEFORE_VIEW moved before their view; without that view the
// item stays where it is
export function placeAmongViews<T extends SubItemPlace>(items: readonly T[]): T[] {
  const moved = items.filter((it) => it.stage && BEFORE_VIEW[it.stage] && items.some((v) => v.view === BEFORE_VIEW[it.stage!]));
  const out = items.filter((it) => !moved.includes(it));
  for (const it of moved) out.splice(out.findIndex((v) => v.view === BEFORE_VIEW[it.stage!]), 0, it);
  return out;
}

// What the elevations of a domain show on a wall; the other layer is switched on by hand (the
// eye in the "On the wall" table)
export const WALL_LAYERS: Readonly<Record<string, WallLayers>> = {
  elevations: { electrical: true, water: false },
  plumbing_elevations: { electrical: false, water: true },
};

export interface Section {
  key: string;        // the domain key, or "sheet:<first page>" for a tab of its own
  domain: boolean;
  tabs: SheetTab[];   // the second level, in order
}

// Sections of the tabs, in sheet order; a domain stands where its first tab is
export function sections(tabs: readonly SheetTab[]): Section[] {
  const out: Section[] = [];
  for (const tb of tabs) {
    const domain = DOMAINS.find((d) => d.stages.includes(tb.stage ?? ""));
    if (domain) {
      let s = out.find((x) => x.domain && x.key === domain.key);
      if (!s) out.push(s = { key: domain.key, domain: true, tabs: [] });
      s.tabs.push(tb);
    } else out.push({ key: `sheet:${tb.pages[0]}`, domain: false, tabs: [tb] });
  }
  return out;
}

// The section a tab is open in
export function sectionOf(all: readonly Section[], tab: SheetTab | null): Section | null {
  return tab ? all.find((s) => s.tabs.includes(tab)) ?? null : null;
}

// Wall layers of an elevations sheet by its topic
export const wallLayersOf = (stage: string | undefined): WallLayers | null => WALL_LAYERS[stage ?? ""] ?? null;

// Services of a project: a service key is a domain key ("demolition" has no sheets yet). An old
// server sends no list: every service is on
export type Services = readonly string[] | undefined;
export const serviceOn = (services: Services, domain: string): boolean => !services || services.includes(domain);

// The domain of a sheet topic; the views of the "Electrical" tab (lighting, wiring) are electrical
export const domainOf = (stage: string | undefined): string | null => {
  const st = stage && VIEWS.has(stage) ? "electrical" : stage ?? "";
  return DOMAINS.find((d) => d.stages.includes(st))?.key ?? null;
};

// A sheet the services show: a sheet outside every domain (plan, furniture) always
export const stageOn = (services: Services, stage: string | undefined): boolean => {
  const d = domainOf(stage);
  return d === null || serviceOn(services, d);
};

// Manifest pages of the switched-on services: what the viewer has as sheets (tabs, one drawing,
// elevations, estimate). May be empty: the viewer then stays on "Overview"
export const servicePages = (pages: readonly ManifestPage[], services: Services): ManifestPage[] =>
  pages.filter((pg) => stageOn(services, pg.stage));

// Wall layers the services have: a layer of a switched-off service is neither drawn nor listed
export const wallLayersOn = (services: Services): WallLayers =>
  ({ electrical: serviceOn(services, "electrical"), water: serviceOn(services, "plumbing") });

// The overview without the blocks of switched-off services: points and panel are electrical,
// plumbing (with its estimate, so not in the project total) is plumbing
export function serviceOverview(overview: Overview, services: Services): Overview {
  const out = { ...overview };
  if (!serviceOn(services, "electrical")) { delete out.points; delete out.panel; }
  if (!serviceOn(services, "plumbing")) delete out.plumbing;
  return out;
}
