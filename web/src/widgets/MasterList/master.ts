// What the master switch cuts: the groups of the project, always in panel order. Quick picks:
// "all but the always-on" — the rule of the panel (master.py: fridge, boiler, router… stay on);
// "lighting only" — the lights; anything else is "by hand"

import type { OverviewMaster } from "@/shared/types";

export type MasterPreset = "rule" | "light" | "manual";

export const masterOn = (m: OverviewMaster) => m.items.filter((g) => g.on).map((g) => g.id);

export const masterRule = (m: OverviewMaster) => m.items.filter((g) => !g.keep).map((g) => g.id);

export const masterLight = (m: OverviewMaster) => m.items.filter((g) => g.kind === "light").map((g) => g.id);

export function toggleMaster(m: OverviewMaster, value: string[], id: string): string[] {
  const next = value.includes(id) ? value.filter((g) => g !== id) : [...value, id];
  return m.items.map((g) => g.id).filter((g) => next.includes(g));
}

export function masterPreset(m: OverviewMaster, value: string[]): MasterPreset {
  const same = (ids: string[]) => ids.length > 0 && ids.join() === value.join();
  if (same(masterRule(m))) return "rule";
  return same(masterLight(m)) ? "light" : "manual";
}
