// Wiring variants from the manifest: the "mode-route-distribution" key and summary lookup

import type { VariantConduit, VariantDistribution, VariantMode, VariantPath, VariantPlaster, VariantRoute, Variants, VariantSummary } from "@/shared/types";

export const MODES: VariantMode[] = ["economy", "standard", "proper"];
export const ROUTES: VariantRoute[] = ["ceiling", "floor"];

export function parseKey(key: string): { mode: VariantMode; route: VariantRoute } {
  const [mode, route] = key.split("-");
  return {
    mode: (MODES as string[]).includes(mode) ? (mode as VariantMode) : "standard",
    route: (ROUTES as string[]).includes(route) ? (route as VariantRoute) : "ceiling",
  };
}

// The chosen set comes first in the summary: its neighbours with another plaster or rough light
// share its key (those are not in the key)
export const activeSummary = (v: Variants): VariantSummary | undefined => v.items.find((s) => s.key === v.active);

// The breakers step of the wizard is the mode: after the wizard's own options (path, conduit)
// a mode decides only the panel scheme and the split by lines (panel.MODE_SCHEME, lines.py)
export type VariantBreakers = "simple" | "groups" | "lines";
const BREAKERS: Record<VariantMode, VariantBreakers> = { economy: "simple", standard: "groups", proper: "lines" };
export const breakersOf = (mode: VariantMode): VariantBreakers => BREAKERS[mode];
// The panel scheme (overview.panel.scheme, panel.MODE_SCHEME) as the breakers step names it
const SCHEME_BREAKERS: Record<"economy" | "standard" | "premium", VariantBreakers> = { economy: "simple", standard: "groups", premium: "lines" };
export const breakersOfScheme = (scheme: "economy" | "standard" | "premium"): VariantBreakers => SCHEME_BREAKERS[scheme];
export const modeOfBreakers = (breakers: string | undefined): VariantMode | undefined =>
  MODES.find((m) => BREAKERS[m] === breakers);

// A variant as a set of options
export interface VariantChoice {
  mode: VariantMode;
  route: VariantRoute;
  distribution: VariantDistribution;
  path: VariantPath;
  conduit: VariantConduit | null;  // null: "don't know", as the mode gives (modeConduit)
  plaster: VariantPlaster;
  rough_light: boolean;
}

type Options = Pick<VariantChoice, "path" | "plaster" | "rough_light"> & { conduit: VariantConduit };

// Conduit of a mode without its own choice (schema.mode_conduit): premium, on the ceiling
export const modeConduit = (mode: VariantMode): VariantConduit => (mode === "proper" ? "ceiling" : "none");

// An older build said yes or no for the ceiling
const conduitOf = (c: VariantSummary["conduit"], mode: VariantMode): VariantConduit =>
  (typeof c === "boolean" ? (c ? "ceiling" : "none") : c ?? modeConduit(mode));

// Options of a summary; an older build has path and conduit by the mode (schema.mode_path)
export const optionsOf = (s: VariantSummary | undefined, mode: VariantMode): Options => ({
  path: s?.path ?? (mode === "economy" ? "shortest" : "right"),
  conduit: conduitOf(s?.conduit, mode),
  plaster: s?.plaster ?? "after",
  rough_light: s?.rough_light ?? false,
});

// The summary of exactly this set: only the chosen one and its neighbours are computed
export const findChoice = (v: Variants, c: VariantChoice): VariantSummary | undefined =>
  v.items.find((s) => {
    const o = optionsOf(s, s.mode);
    return s.mode === c.mode && s.route === c.route && s.distribution === c.distribution && o.path === c.path
      && o.conduit === (c.conduit ?? modeConduit(c.mode))
      && o.plaster === c.plaster && o.rough_light === c.rough_light;
  });

// Routes the project has: the summary is built only for them (electrical.yaml routes).
// An empty summary means both, so the toggle does not disappear
export function availableRoutes(v: Variants): VariantRoute[] {
  const present = ROUTES.filter((route) => v.items.some((s) => s.route === route));
  return present.length ? present : ROUTES;
}

// A neighbour of the chosen set (pipeline.variant_block): the same set with one wizard step
// answered otherwise. A change of breakers (the mode) also brings the conduit of that mode when
// the conduit is "don't know": it is still the breakers step
export type NeighbourStep = "route" | "distribution" | "path" | "conduit" | "plaster" | "rough" | "breakers";
export const NEIGHBOUR_STEPS: NeighbourStep[] = ["route", "distribution", "path", "conduit", "plaster", "rough", "breakers"];

export interface Neighbour {
  step: NeighbourStep;
  value: string;  // the other answer, as the wizard names its card
  summary: VariantSummary;
}

function changedStep(s: VariantSummary, base: VariantSummary): Neighbour | null {
  if (s.mode !== base.mode) return { step: "breakers", value: breakersOf(s.mode), summary: s };
  const a = optionsOf(s, s.mode), b = optionsOf(base, base.mode);
  const pairs: [NeighbourStep, string, string][] = [
    ["route", s.route, base.route],
    ["distribution", s.distribution ?? "boxes", base.distribution ?? "boxes"],
    ["path", a.path, b.path],
    ["conduit", a.conduit, b.conduit],
    ["plaster", a.plaster, b.plaster],
    ["rough", a.rough_light ? "yes" : "no", b.rough_light ? "yes" : "no"],
  ];
  const diff = pairs.filter(([, x, y]) => x !== y);
  return diff.length === 1 ? { step: diff[0][0], value: diff[0][1], summary: s } : null;
}

// The neighbours in the order of the wizard steps; an older build (the six modes) has none
export function neighbours(v: Variants): Neighbour[] {
  const base = activeSummary(v);
  if (!base) return [];
  const found = v.items.filter((s) => s !== base).map((s) => changedStep(s, base)).filter((n): n is Neighbour => n !== null);
  return found.sort((x, y) => NEIGHBOUR_STEPS.indexOf(x.step) - NEIGHBOUR_STEPS.indexOf(y.step));
}
