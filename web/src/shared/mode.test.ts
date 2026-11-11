import { beforeEach, describe, expect, it, vi } from "vitest";
import { defaultMode, modeDrawerTabs, modeTabs, rememberMode, savedMode, stageShown } from "./mode";
import type { SheetTab } from "./tabs";

const store = new Map<string, string>();
vi.stubGlobal("localStorage", {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => { store.set(k, v); },
});

describe("default mode by account", () => {
  it("firm and local viewing — engineering", () => {
    expect(defaultMode(null)).toBe("engineering");
    expect(defaultMode({ plan: "pro", visitor: false })).toBe("engineering");
    expect(defaultMode({ plan: null, visitor: true })).toBe("engineering");
  });
  it("homeowner, access code, no plan yet — simple", () => {
    expect(defaultMode({ plan: "client", visitor: false })).toBe("simple");
    expect(defaultMode({ plan: "pro", visitor: false, code: true })).toBe("simple");
    expect(defaultMode({ plan: null, visitor: false })).toBe("simple");
  });
});

describe("remembered mode", () => {
  beforeEach(() => store.clear());
  it("the choice wins over the account", () => {
    rememberMode("engineering");
    expect(savedMode({ plan: "client", visitor: false })).toBe("engineering");
  });
  it("garbage in storage — by account", () => {
    store.set("ui-mode", "expert");
    expect(savedMode({ plan: "client", visitor: false })).toBe("simple");
  });
});

describe("tabs of the mode", () => {
  const stages: Record<number, string> = { 0: "plan", 1: "electrical", 2: "lighting", 3: "wiring", 4: "panel", 5: "elevations", 6: "points" };
  const tabs: SheetTab[] = [
    { name: "План", stage: "plan", pages: [0], views: false },
    { name: "Электрика", stage: "electrical", pages: [1, 2, 3], views: true },
    { name: "Щит", stage: "panel", pages: [4], views: false },
    { name: "Развёртки", stage: "elevations", pages: [5], views: false },
    { name: "Точки", stage: "points", pages: [6], views: false },
  ];
  const stageOf = (i: number) => stages[i];

  it("engineering — everything", () => {
    expect(modeTabs(tabs, stageOf, "engineering")).toEqual(tabs);
  });
  it("simple — without wiring view, panel and points", () => {
    const out = modeTabs(tabs, stageOf, "simple");
    expect(out.map((t) => t.name)).toEqual(["План", "Электрика", "Развёртки"]);
    expect(out[1].pages).toEqual([1, 2]);
  });
  it("sheets without a topic stay", () => {
    expect(stageShown("simple", undefined)).toBe(true);
    expect(stageShown("simple", "wiring")).toBe(false);
  });
  it("simple header keeps only the questions", () => {
    expect(modeDrawerTabs("simple")).toEqual(["questions"]);
    expect(modeDrawerTabs("engineering")).toEqual(["questions", "sources", "project"]);
  });
});
