import { describe, expect, it } from "vitest";
import { sheetTabs, shownView, tabOf, tabViews, viewSheet } from "./tabs";
import type { ManifestPage } from "./types";

const page = (index: number, name: string, stage?: string): ManifestPage =>
  ({ index, name, stage, format: "A2", size: [594, 420], file: `pages/${index}.json` });

describe("sheetTabs", () => {
  it("складывает продолжения одной темы в одну вкладку", () => {
    const tabs = sheetTabs([
      page(1, "01 План", "plan"),
      page(2, "02 Електрика", "electrical"),
      page(7, "07 Розгортки", "elevations"),
      page(8, "08 Розгортки (продовження)", "elevations"),
      page(9, "09 Розгортки (продовження)", "elevations"),
    ]);
    expect(tabs.map((t) => t.name)).toEqual(["План", "Електрика", "Розгортки"]);
    expect(tabs[2].pages).toEqual([7, 8, 9]);
    expect(tabOf(tabs, 8)?.name).toBe("Розгортки");
    expect(tabOf(tabs, null)).toBeNull();
  });

  it("электрика, освещение и проводка — одна вкладка с видами", () => {
    const tabs = sheetTabs([
      page(1, "01 План", "plan"),
      page(2, "02 Електрика", "electrical"),
      page(3, "03 Освітлення", "lighting"),
      page(4, "04 Проводка", "wiring"),
      page(5, "05 Щит", "panel"),
    ]);
    expect(tabs.map((t) => [t.name, t.pages, t.views])).toEqual([
      ["План", [1], false], ["Електрика", [2, 3, 4], true], ["Щит", [5], false],
    ]);
    expect(tabOf(tabs, 4)?.name).toBe("Електрика");
    // The tab label follows the topic, in the interface language
    expect(tabs.map((t) => t.stage)).toEqual(["plan", "electrical", "panel"]);
  });

  it("сантехника — своя вкладка после щита, не вид электрики", () => {
    const tabs = sheetTabs([
      page(2, "02 Електрика", "electrical"),
      page(4, "04 Проводка", "wiring"),
      page(5, "05 Щит", "panel"),
      page(6, "06 Сантехніка", "plumbing"),
    ]);
    expect(tabs.map((t) => [t.stage, t.pages, t.views])).toEqual([
      ["electrical", [2, 4], true], ["panel", [5], false], ["plumbing", [6], false],
    ]);
  });

  it("развёртки — страницы, а не виды", () => {
    const [t] = sheetTabs([page(7, "07", "elevations"), page(8, "08", "elevations")]);
    expect(t.views).toBe(false);
  });

  it("листы без темы не склеиваются", () => {
    expect(sheetTabs([page(1, "01"), page(2, "02")]).length).toBe(2);
  });
});

describe("views of the Electrical tab", () => {
  const stages: Record<number, string> = { 2: "electrical", 3: "lighting", 4: "wiring" };
  const stageOf = (i: number) => stages[i];
  const [tab] = sheetTabs([page(2, "02 Электрика", "electrical"), page(3, "03 Освещение", "lighting"), page(4, "04 Проводка", "wiring")]);

  it("goes by system: lighting, sockets, low voltage, wiring", () => {
    expect(tabViews(tab, stageOf, true, false)).toEqual([
      { key: "lighting", index: 2 }, { key: "electrical", index: 2 }, { key: "low", index: 2 }, { key: "wiring", index: 4 },
    ]);
    expect(tabViews(tab, stageOf, false, false).map((v) => v.key)).toEqual(["lighting", "electrical", "wiring"]);
  });

  it("lighting is its lines on the electrical sheet or its links on the lighting sheet", () => {
    expect(viewSheet(tab, stageOf, "lighting", false)).toBe(2);
    expect(viewSheet(tab, stageOf, "lighting", true)).toBe(3);
    const [onlyLinks] = sheetTabs([page(3, "03 Освещение", "lighting"), page(4, "04 Проводка", "wiring")]);
    expect(viewSheet(onlyLinks, stageOf, "lighting", false)).toBe(3);  // no electrical sheet: the links
  });

  it("names the view shown by the sheet and what the electrical sheet shows", () => {
    expect(shownView("electrical", "light")).toBe("lighting");
    expect(shownView("electrical", "low")).toBe("low");
    expect(shownView("electrical", "sockets")).toBe("electrical");
    expect(shownView("lighting", "sockets")).toBe("lighting");
    expect(shownView("wiring", "light")).toBe("wiring");
  });
});
