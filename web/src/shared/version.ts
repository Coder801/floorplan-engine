// Version check: a tab opened before a deploy keeps the old bundle, reads the new API and
// silently breaks. The build number is baked into the bundle (__BUILD_ID__, vite.config.ts)
// and served at /version.json; if they differ, it is time to reload. Not checked in development ("dev").

declare const __BUILD_ID__: string;
export const BUILD_ID = __BUILD_ID__;

// Product version (package.json, vite.config.ts) and stage: alpha for now, internal, features
// still change. Shown in settings and next to the name (i18n app.stage)
declare const __APP_VERSION__: string;
export const APP_VERSION = __APP_VERSION__;
export const STAGE = "alpha";
// The product name is a brand: always in Latin letters and the brand font ($brand), the same in
// every language; it is not in the i18n dictionaries (decision 2026-11-03)
export const BRAND = "Shtroba";

// .epd format version this page understands (artifact.FORMAT_VERSION)
export const FORMAT_VERSION = 1;

const EVERY_MS = 5 * 60_000;

export async function latestBuild(): Promise<string | null> {
  try {
    const r = await fetch("/version.json", { cache: "no-store" });
    return r.ok ? ((await r.json()) as { build?: string }).build ?? null : null;
  } catch {
    return null;  // no network is not a reason to ask for a reload
  }
}

// Watch for deploys: every 5 minutes and when the tab is visible again; onStale fires once
export function watchBuild(onStale: () => void): () => void {
  if (BUILD_ID === "dev") return () => {};
  let done = false;
  const check = async () => {
    if (done || document.hidden) return;
    const b = await latestBuild();
    if (b && b !== BUILD_ID) { done = true; onStale(); }
  };
  const timer = setInterval(check, EVERY_MS);
  document.addEventListener("visibilitychange", check);
  check();
  return () => { clearInterval(timer); document.removeEventListener("visibilitychange", check); };
}
