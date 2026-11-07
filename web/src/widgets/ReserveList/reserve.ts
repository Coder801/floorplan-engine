// The chosen groups of the backup bus: always in panel order, so a comparison means "the same set"

import type { OverviewReserve } from "@/shared/types";

export const reserveOn = (r: OverviewReserve) => r.items.filter((g) => g.on).map((g) => g.id);

export function toggleGroup(r: OverviewReserve, value: string[], id: string): string[] {
  const next = value.includes(id) ? value.filter((g) => g !== id) : [...value, id];
  return r.items.map((g) => g.id).filter((g) => next.includes(g));
}

// From this share of the source power the sum warns that the limit is near
const NEAR_LIMIT = 0.8;

export type ReserveLevel = "ok" | "near" | "over";

// Over only above the limit, as the panel weak spot w_backup; no limit known: nothing to compare
export function reserveLevel(watts: number, limitKw: number | null): ReserveLevel {
  if (limitKw === null) return "ok";
  if (watts > limitKw * 1000) return "over";
  return watts >= limitKw * 1000 * NEAR_LIMIT ? "near" : "ok";
}

export const reservePower = (r: OverviewReserve, value: string[]) =>
  r.items.reduce((sum, g) => sum + (value.includes(g.id) ? g.power : 0), 0);
