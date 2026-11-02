// Варианты проводки из манифеста: ключ «режим-трасса-разводка» и поиск сводки

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
