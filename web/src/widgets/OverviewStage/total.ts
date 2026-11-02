// Итог проекта на вкладке «Общие сведения»: смета электрики выбранного варианта проводки
// (variants) плюс смета сантехники (overview.plumbing.estimate) — сантехника от варианта не
// зависит. Нет ни одной сметы — итога нет.
import type { OverviewPlumbing, VariantSummary } from "@/shared/types";

export interface ProjectTotal {
  total: number;
  currency: string;
  electrical?: number;  // нет — электрики в проекте нет
  plumbing?: number;    // нет — сантехники нет
  unpriced: number;     // позиций без цены в обеих сметах
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
