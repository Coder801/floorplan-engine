// Sections of the header: the first menu level. A domain (electrical, plumbing, later walls and
// so on) gathers its sheet tabs (shared/tabs.ts) into one section, its sheets are the second
// level under the header. A tab outside every domain (plan, furniture) is a section of its own.
// Elevations are shared: the wall engine is one, so the tab is in every domain of the project,
// and the domain only picks the layers seen on the wall (WALL_LAYERS).

import type { WallLayers } from "./store";
import type { SheetTab } from "./tabs";

// Domains in menu order; stages are tab topics (SheetTab.stage). A new domain is a row here
export const DOMAINS: readonly { key: string; stages: readonly string[] }[] = [
  { key: "electrical", stages: ["electrical", "panel"] },
  { key: "plumbing", stages: ["plumbing"] },
];

// Tab topics that belong to every domain
export const SHARED_STAGES: ReadonlySet<string> = new Set(["elevations"]);

// What a domain shows on a wall when the project has several; the other layers are switched on
// by hand (the eye in the "On the wall" table)
export const WALL_LAYERS: Readonly<Record<string, WallLayers>> = {
  electrical: { electrical: true, water: false },
  plumbing: { electrical: false, water: true },
};

export interface Section {
  key: string;        // the domain key, or "sheet:<first page>" for a tab of its own
  domain: boolean;
  tabs: SheetTab[];   // the second level, in order
}

// Sections of the tabs, in sheet order; a domain stands where its first tab is. Without any
// domain a shared tab is a section of its own
export function sections(tabs: readonly SheetTab[]): Section[] {
  const out: Section[] = [];
  const shared: SheetTab[] = [];
  for (const tb of tabs) {
    const domain = DOMAINS.find((d) => d.stages.includes(tb.stage ?? ""));
    if (domain) {
      let s = out.find((x) => x.domain && x.key === domain.key);
      if (!s) out.push(s = { key: domain.key, domain: true, tabs: [] });
      s.tabs.push(tb);
    } else if (SHARED_STAGES.has(tb.stage ?? "")) shared.push(tb);
    else out.push({ key: `sheet:${tb.pages[0]}`, domain: false, tabs: [tb] });
  }
  const domains = out.filter((s) => s.domain);
  if (domains.length) for (const s of domains) s.tabs.push(...shared);
  else for (const tb of shared) out.push({ key: `sheet:${tb.pages[0]}`, domain: false, tabs: [tb] });
  return out;
}

// The section a tab is open in: a shared tab is in several, then the one named (the domain the
// user came from), else the first
export function sectionOf(all: readonly Section[], tab: SheetTab | null, preferred: string | null): Section | null {
  if (!tab) return null;
  const own = all.filter((s) => s.tabs.includes(tab));
  return own.find((s) => s.key === preferred) ?? own[0] ?? null;
}

// Wall layers of a section: only when the walls are shared by several domains
export function wallLayersOf(all: readonly Section[], section: Section | null): WallLayers | null {
  if (!section?.domain) return null;
  const withWalls = all.filter((s) => s.domain && s.tabs.some((tb) => SHARED_STAGES.has(tb.stage ?? "")));
  return withWalls.length > 1 ? WALL_LAYERS[section.key] ?? null : null;
}
