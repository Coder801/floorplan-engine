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

// Quick picks: "lighting only" — the least that keeps the flat usable; "most by power" — as many
// groups as the source holds: lighting first, then sockets, then heavy, smaller ones first, while
// the sum stays within the source power. Without a known power heavy loads are left out: there is
// nothing to check them against. "manual": a set that is neither of them.
export type ReservePreset = "light" | "max" | "manual";

export const lightOnly = (r: OverviewReserve) => r.items.filter((g) => g.kind === "light").map((g) => g.id);

const ORDER = { light: 0, sockets: 1, heavy: 2 } as const;

export function mostByPower(r: OverviewReserve): string[] {
  const budget = r.limit_kw === null ? Infinity : r.limit_kw * 1000;
  const items = r.items
    .filter((g) => r.limit_kw !== null || g.kind !== "heavy")
    .map((g, k) => ({ g, k }))
    .sort((a, b) => ORDER[a.g.kind ?? "sockets"] - ORDER[b.g.kind ?? "sockets"] || a.g.power - b.g.power || a.k - b.k);
  let sum = 0;
  const on = new Set<string>();
  for (const { g } of items) {
    if (sum + g.power > budget) continue;
    sum += g.power;
    on.add(g.id);
  }
  return r.items.map((g) => g.id).filter((id) => on.has(id));
}

export function presetOf(r: OverviewReserve, value: string[]): ReservePreset {
  const same = (ids: string[]) => ids.length > 0 && ids.join() === value.join();
  if (same(lightOnly(r))) return "light";
  return same(mostByPower(r)) ? "max" : "manual";
}
