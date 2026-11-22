import { beforeEach, describe, expect, it, vi } from "vitest";
import { markTourSeen, TOUR_KEY, tourForced, tourSeen, withoutTourParam } from "./seen";

// Tests run in Node: an in-memory localStorage
const store = new Map<string, string>();
vi.stubGlobal("localStorage", {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => { store.set(k, v); },
});

describe("client tour seen", () => {
  beforeEach(() => store.clear());

  it("is not seen in a fresh browser", () => {
    expect(tourSeen()).toBe(false);
  });

  it("is remembered once seen", () => {
    markTourSeen();
    expect(tourSeen()).toBe(true);
    expect(store.get(TOUR_KEY)).toBe("seen");
  });
});

describe("?tour in the address", () => {
  it("forces the tour with or without a value", () => {
    expect(tourForced("?tour")).toBe(true);
    expect(tourForced("?a=1&tour=1")).toBe(true);
    expect(tourForced("")).toBe(false);
    expect(tourForced("?tours=1")).toBe(false);
  });

  it("is dropped from the address, the hash and other parameters stay", () => {
    expect(withoutTourParam("http://127.0.0.1:5173/?tour#kv42")).toBe("http://127.0.0.1:5173/#kv42");
    expect(withoutTourParam("http://h/?a=1&tour=1#p")).toBe("http://h/?a=1#p");
  });
});
