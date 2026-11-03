// Project total on the "Overview" tab: the electrical estimate of the chosen wiring variant
// (variants) plus the plumbing estimate (overview.plumbing.estimate); plumbing does not depend
// on the variant. No estimate at all means no total.
import type { OverviewPlumbing, VariantSummary } from "@/shared/types";

export interface ProjectTotal {
  total: number;
  currency: string;
  electrical?: number;  // missing: the project has no electrical
  plumbing?: number;    // missing: no plumbing
  unpriced: number;     // items without a price in both estimates
}

export function projectTotal(variant?: VariantSummary, plumbing?: OverviewPlumbing["estimate"]): ProjectTotal | null {
  if (!variant && !plumbing) return null;
  return {
    total: (variant?.total ?? 0) + (plumbing?.total ?? 0),
    currency: variant?.currency ?? plumbing?.currency ?? "",
    electrical: variant?.total,
    plumbing: plumbing?.total,
    unpriced: (variant?.unpriced ?? 0) + (plumbing?.unpriced ?? 0),
  };
}
