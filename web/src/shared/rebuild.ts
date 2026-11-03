// The project was rebuilt while the tab is open (build in a terminal, an edit in another tab):
// the sheets in page memory are stale. The build time (built, out/report.json) is checked every
// EVERY_MS and when the tab becomes visible again; if it changed, onRebuilt (reload the sheets).

const EVERY_MS = 10_000;

// built is the build time the sheets were opened with; load fetches the latest build time from the API
export function watchRebuild(load: () => Promise<number | null>, built: number | null,
                             onRebuilt: () => void, every = EVERY_MS): () => void {
  let done = false;
  const check = async () => {
    if (done || document.hidden) return;
    let now: number | null;
    try { now = await load(); } catch { return; }  // no network is not a reason to reload
    if (!done && now !== null && now !== built) { done = true; onRebuilt(); }
  };
  const timer = setInterval(check, every);
  document.addEventListener("visibilitychange", check);
  window.addEventListener("focus", check);
  return () => {
    done = true;
    clearInterval(timer);
    document.removeEventListener("visibilitychange", check);
    window.removeEventListener("focus", check);
  };
}
