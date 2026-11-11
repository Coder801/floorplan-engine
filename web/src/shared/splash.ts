// Splash over the whole screen (index.html, #splash): the mark until the app is ready. hideSplash
// starts the exit — both corners erased clockwise, then a fade — and removes the element when it
// is over. Called by whoever shows the first real screen: the login (Gate) or the projects
// (Viewer); a second call does nothing. A stuck load still lets the page through after GIVE_UP_MS.

export const SPLASH_OUT_MS = 900;   // erase .6 s + fade .3 s after .55 s (index.html)
const GIVE_UP_MS = 15_000;

export function hideSplash(doc: Document = document) {
  const el = doc.getElementById("splash");
  if (!el || el.dataset.state === "out") return;
  el.dataset.state = "out";
  el.setAttribute("aria-busy", "false");
  const reduced = doc.defaultView?.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  setTimeout(() => el.remove(), reduced ? 300 : SPLASH_OUT_MS);
}

if (typeof document !== "undefined") setTimeout(() => hideSplash(), GIVE_UP_MS);
