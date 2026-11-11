import { afterEach, describe, expect, it, vi } from "vitest";
import { hideSplash, SPLASH_OUT_MS } from "./splash";

// A stand-in for the document with the #splash element (tests run in Node)
function page(reduced = false) {
  const el = {
    dataset: {} as Record<string, string>,
    attrs: {} as Record<string, string>,
    removed: false,
    setAttribute(k: string, v: string) { this.attrs[k] = v; },
    remove() { this.removed = true; },
  };
  const doc = {
    getElementById: (id: string) => (id === "splash" && !el.removed ? el : null),
    defaultView: { matchMedia: () => ({ matches: reduced }) },
  } as unknown as Document;
  return { el, doc };
}

describe("splash", () => {
  afterEach(() => { vi.useRealTimers(); });

  it("starts the exit, then removes itself after the animation", () => {
    vi.useFakeTimers();
    const { el, doc } = page();
    hideSplash(doc);
    expect(el.dataset.state).toBe("out");
    expect(el.attrs["aria-busy"]).toBe("false");
    vi.advanceTimersByTime(SPLASH_OUT_MS - 1);
    expect(el.removed).toBe(false);
    vi.advanceTimersByTime(1);
    expect(el.removed).toBe(true);
  });

  it("a second call does nothing; reduced motion leaves sooner", () => {
    vi.useFakeTimers();
    const { el, doc } = page(true);
    hideSplash(doc);
    hideSplash(doc);
    vi.advanceTimersByTime(300);
    expect(el.removed).toBe(true);
  });

  it("no splash on the page — no error", () => {
    expect(() => hideSplash({ getElementById: () => null } as unknown as Document)).not.toThrow();
  });
});
