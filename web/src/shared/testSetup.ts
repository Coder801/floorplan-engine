// Setup of component tests (*.test.tsx, jsdom; vite.config.ts, test.projects): testing-library
// matchers (toBeDisabled, toHaveAccessibleName…); a clean DOM, storage, address and stubs (fetch —
// testApi.ts) after every test; the browser APIs jsdom lacks; the interface in Russian — the same
// i18n start as Storybook (.storybook/preview.tsx), so a test finds the strings of ru.ts.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom has no matchMedia: no media query matches (consts.ts reads prefers-reduced-motion on import)
window.matchMedia ??= (query: string) => ({
  matches: false, media: query, onchange: null,
  addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {},
  dispatchEvent: () => false,
});

// …nor ResizeObserver: nothing is ever resized there (the header underline measures its tabs)
window.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} };
// …nor scrolling an element into view (the side panel scrolls to the row of the hovered object)
Element.prototype.scrollIntoView ??= () => {};

const { setLanguage } = await import("@/shared/i18n");
setLanguage("ru");

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  localStorage.clear();
  sessionStorage.clear();
  history.replaceState(null, "", "/");
});
