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

// A mode as a preset: without the options of the setup wizard
const presetKey = (mode: VariantMode, route: VariantRoute) => `${mode}-${route}-boxes`;

export const findVariant = (v: Variants, mode: VariantMode, route: VariantRoute): VariantSummary | undefined =>
  v.items.find((s) => s.key === presetKey(mode, route));

export const activeSummary = (v: Variants): VariantSummary | undefined => v.items.find((s) => s.key === v.active);

// The chosen variant is a set from the setup wizard, not one of the modes
export function isCustom(v: Variants): boolean {
  const { mode, route } = parseKey(v.active);
  return v.active !== presetKey(mode, route);
}

// The breakers step of the wizard is the mode: after the wizard's own options (path, conduit)
// a mode decides only the panel scheme and the split by lines (panel.MODE_SCHEME, lines.py)
export type VariantBreakers = "simple" | "groups" | "lines";
const BREAKERS: Record<VariantMode, VariantBreakers> = { economy: "simple", standard: "groups", proper: "lines" };
export const breakersOf = (mode: VariantMode): VariantBreakers => BREAKERS[mode];
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

// The summary of exactly this set: only the modes and the chosen one are computed
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
