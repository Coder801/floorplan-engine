// Wiring variants from the manifest: the "mode-route-distribution" key and summary lookup

import type { VariantMode, VariantRoute, Variants, VariantSummary } from "@/shared/types";

export const MODES: VariantMode[] = ["economy", "standard", "proper"];
export const ROUTES: VariantRoute[] = ["ceiling", "floor"];

export function parseKey(key: string): { mode: VariantMode; route: VariantRoute } {
  const [mode, route] = key.split("-");
  return {
    mode: (MODES as string[]).includes(mode) ? (mode as VariantMode) : "standard",
    route: (ROUTES as string[]).includes(route) ? (route as VariantRoute) : "ceiling",
  };
}

export const findVariant = (v: Variants, mode: VariantMode, route: VariantRoute): VariantSummary | undefined =>
  v.items.find((s) => s.mode === mode && s.route === route && s.distribution === "boxes");

// Routes the project has: the summary is built only for them (electrical.yaml routes).
// An empty summary means both, so the toggle does not disappear
export function availableRoutes(v: Variants): VariantRoute[] {
  const present = ROUTES.filter((route) => v.items.some((s) => s.route === route));
  return present.length ? present : ROUTES;
}
