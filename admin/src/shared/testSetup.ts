// Setup of component tests (*.test.tsx, jsdom; vite.config.ts, test.projects): testing-library
// matchers (toBeDisabled, toHaveAccessibleName…), a clean DOM, address and stubs after every test.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  location.hash = "";
});
