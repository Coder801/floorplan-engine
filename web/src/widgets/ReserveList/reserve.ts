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

// Installed power of the chosen groups
export const reservePower = (r: OverviewReserve, value: string[]) =>
  r.items.reduce((sum, g) => sum + (value.includes(g.id) ? g.power : 0), 0);

type Item = OverviewReserve["items"][number];
// Share in the peak: an older build has none, the group counts whole
const share = (g: Item) => ({ steady: g.steady ?? g.power, peak: g.peak ?? 0 });

// Design peak (decision 2026-11-11, loads.backup_peak): steady parts of the chosen groups and one
// occasional appliance, the largest — on a backup source they run one at a time
export function peakOf(items: Item[]): number {
  let steady = 0;
  let peak = 0;
  for (const g of items) {
    const s = share(g);
    steady += s.steady;
    peak = Math.max(peak, s.peak);
  }
  return steady + peak;
}

export const reservePeak = (r: OverviewReserve, value: string[]) => peakOf(r.items.filter((g) => value.includes(g.id)));

// Quick picks: "lighting only" — the least that keeps the flat usable; "most by power" — as many
// groups as the source holds: lighting first, then sockets, then heavy, smaller ones first, while
// the design peak stays within the source power. Without a known power heavy loads are left out: there is
// nothing to check them against. "manual": a set that is neither of them.
export type ReservePreset = "light" | "max" | "manual";

export const lightOnly = (r: OverviewReserve) => r.items.filter((g) => g.kind === "light").map((g) => g.id);

const ORDER = { light: 0, sockets: 1, heavy: 2 } as const;

export function mostByPower(r: OverviewReserve): string[] {
  const budget = r.limit_kw === null ? Infinity : r.limit_kw * 1000;
  const items = r.items
    .filter((g) => r.limit_kw !== null || g.kind !== "heavy")
    .map((g, k) => ({ g, k }))
    .sort((a, b) => ORDER[a.g.kind ?? "sockets"] - ORDER[b.g.kind ?? "sockets"] || peakOf([a.g]) - peakOf([b.g]) || a.k - b.k);
  const chosen: Item[] = [];
  for (const { g } of items) {
    if (peakOf([...chosen, g]) <= budget) chosen.push(g);
  }
  const on = new Set(chosen.map((g) => g.id));
  return r.items.map((g) => g.id).filter((id) => on.has(id));
}

export function presetOf(r: OverviewReserve, value: string[]): ReservePreset {
  const same = (ids: string[]) => ids.length > 0 && ids.join() === value.join();
  if (same(lightOnly(r))) return "light";
  return same(mostByPower(r)) ? "max" : "manual";
}
