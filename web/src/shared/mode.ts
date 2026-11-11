// Interface mode: simple (homeowner, studio client) or engineering (studio, electrician).
// Tested with users: ordinary people found the full viewer too complex, engineers found it
// fine. The simple mode only hides: the same drawing, tables, estimate and questions, without
// the engineering sheets (wiring, panel, points print sheet), layers, sources and the project
// report, and without the DXF. The choice is in settings, like the language, and is remembered
// in the browser; without a choice — by account type.

import { DRAWER_TABS, type DrawerTab } from "./consts";
import { remember, remembered } from "./palette";
import type { SheetTab } from "./tabs";

export const UI_MODES = ["simple", "engineering"] as const;
export type UiMode = (typeof UI_MODES)[number];

const KEY = "ui-mode";

// Sheet topics the simple mode does not show (the wiring page still feeds the "Estimate" tab)
export const ENGINEERING_STAGES: ReadonlySet<string> = new Set(["wiring", "panel", "points"]);

// Who sees what first: a firm (studio) and local viewing (no login, a developer) — engineering;
// "Мой ремонт", an access code, a new account without a plan — simple
export interface ModeAccount { plan: "client" | "pro" | null; visitor: boolean; code?: boolean }
export function defaultMode(account: ModeAccount | null): UiMode {
  if (!account || account.visitor) return "engineering";
  return account.plan === "pro" && !account.code ? "engineering" : "simple";
}

export function savedMode(account: ModeAccount | null): UiMode {
  const m = remembered(KEY);
  return (UI_MODES as readonly string[]).includes(m ?? "") ? (m as UiMode) : defaultMode(account);
}
export const rememberMode = (mode: UiMode) => remember(KEY, mode);

// A sheet the mode shows
export const stageShown = (mode: UiMode, stage: string | undefined) =>
  mode === "engineering" || !ENGINEERING_STAGES.has(stage ?? "");

// Tabs of the mode: hidden sheets leave their tab (the wiring view leaves "Electrical"); a tab
// with nothing left is gone
export function modeTabs(tabs: readonly SheetTab[], stageOf: (i: number) => string | undefined, mode: UiMode): SheetTab[] {
  if (mode === "engineering") return [...tabs];
  return tabs.flatMap((tb) => {
    const pages = tb.pages.filter((i) => stageShown(mode, stageOf(i)));
    return pages.length ? [{ ...tb, pages }] : [];
  });
}

// Header panels of the mode: the simple one keeps only the questions
export const modeDrawerTabs = (mode: UiMode): readonly DrawerTab[] =>
  (mode === "engineering" ? DRAWER_TABS : DRAWER_TABS.filter((k) => k === "questions"));
