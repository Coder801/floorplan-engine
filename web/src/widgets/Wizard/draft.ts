// A wizard choice not applied yet: kept in the tab's sessionStorage, by project, so a page reload
// or a server restart does not lose it. It lives TTL_MS after the last change and only for the
// build it was made on: after a rebuild the choices may no longer fit the project.

import type { Picks, StepId } from "./steps";

export const TTL_MS = 10 * 60 * 1000;

export interface Draft { picks: Picks; step: StepId | "done" }
interface Stored extends Draft { at: number; built: number | null }
type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const keyOf = (project: string) => `wizard:${project}`;
// sessionStorage may be closed (private mode): the wizard then just works without a draft
function session(): Store | null {
  try { return sessionStorage; } catch { return null; }
}

export function saveDraft(project: string, built: number | null, draft: Draft, store = session(), now = Date.now()) {
  const stored: Stored = { ...draft, at: now, built };
  try { store?.setItem(keyOf(project), JSON.stringify(stored)); } catch { /* not kept */ }
}

export function clearDraft(project: string, store = session()) {
  try { store?.removeItem(keyOf(project)); } catch { /* nothing to clear */ }
}

export function loadDraft(project: string, built: number | null, store = session(), now = Date.now()): Draft | null {
  let saved: Stored | null = null;
  try { saved = JSON.parse(store?.getItem(keyOf(project)) ?? "null") as Stored | null; } catch { /* a broken one is dropped */ }
  if (!saved?.picks || saved.built !== built || now - saved.at > TTL_MS) {
    clearDraft(project, store);
    return null;
  }
  return { picks: saved.picks, step: saved.step };
}

export function samePicks(a: Picks, b: Picks): boolean {
  return (Object.keys({ ...a, ...b }) as StepId[]).every((k) => (a[k] ?? "") === (b[k] ?? ""));
}
