import { describe, expect, it } from "vitest";
import { sheetTabs, tabOf } from "./tabs";
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
  });

  it("развёртки — страницы, а не виды", () => {
    const [t] = sheetTabs([page(7, "07", "elevations"), page(8, "08", "elevations")]);
    expect(t.views).toBe(false);
  });

  it("листы без темы не склеиваются", () => {
    expect(sheetTabs([page(1, "01"), page(2, "02")]).length).toBe(2);
  });
});
