// Project total on the "Overview" tab: the electrical estimate of the chosen wiring variant
// (variants) plus the plumbing estimate (overview.plumbing.estimate); plumbing does not depend
// on the variant. No estimate at all means no total. The total is also split into work and
// materials (material prices are a guess for now, decision 2026-11-12).
import { cents } from "@/shared/money";
import type { OverviewPlumbing, VariantSummary } from "@/shared/types";

export interface ProjectTotal {
  total: number;
  currency: string;
  electrical?: number;  // missing: the project has no electrical
  plumbing?: number;    // missing: no plumbing
  unpriced: number;     // items without a price in both estimates
  // The total split into work and materials; missing when an estimate has no split (older build)
  work?: number;
  material?: number;
}

// One part of the split over both estimates: undefined if any present estimate lacks it
function part(key: "work" | "material", ...estimates: ({ work?: number; material?: number } | undefined)[]): number | undefined {
  const present = estimates.filter((e) => e !== undefined);
  if (present.some((e) => e[key] === undefined)) return undefined;
  return cents(present.reduce((sum, e) => sum + (e[key] ?? 0), 0));
}

export function projectTotal(variant?: VariantSummary, plumbing?: OverviewPlumbing["estimate"]): ProjectTotal | null {
  if (!variant && !plumbing) return null;
  return {
    total: cents((variant?.total ?? 0) + (plumbing?.total ?? 0)),
    currency: variant?.currency ?? plumbing?.currency ?? "",
    electrical: variant?.total,
    plumbing: plumbing?.total,
    unpriced: (variant?.unpriced ?? 0) + (plumbing?.unpriced ?? 0),
    work: part("work", variant, plumbing),
    material: part("material", variant, plumbing),
  };
}
