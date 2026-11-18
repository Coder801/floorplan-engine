import { describe, expect, it } from "vitest";
import { placeAmongViews, sectionOf, sections, wallLayersOf } from "./domains";
import { sheetTabs } from "./tabs";
import type { ManifestPage } from "./types";

const page = (index: number, name: string, stage?: string): ManifestPage =>
  ({ index, name, stage, format: "A2", size: [594, 420], file: `pages/${index}.json` });

const full = sheetTabs([
  page(1, "01 План", "plan"),
  page(2, "02 Электрика", "electrical"),
  page(3, "03 Освещение", "lighting"),
  page(4, "04 Проводка", "wiring"),
  page(5, "05 Щит", "panel"),
  page(6, "06 Тёплый пол", "floor_heating"),
  page(7, "07 Сантехника", "plumbing"),
  page(8, "08 Развёртки электрики", "elevations"),
  page(9, "09 Развёртки электрики (продолжение)", "elevations"),
  page(10, "10 Развёртки сантехники", "plumbing_elevations"),
]);

describe("sections", () => {
  it("собирает листы раздела в один пункт, у каждого раздела свои развёртки", () => {
    const all = sections(full);
    expect(all.map((s) => s.key)).toEqual(["sheet:1", "electrical", "plumbing"]);
    expect(all[1].tabs.map((t) => t.stage)).toEqual(["electrical", "panel", "floor_heating", "elevations"]);
    expect(all[1].tabs.at(-1)!.pages).toEqual([8, 9]);
    expect(all[2].tabs.map((t) => t.stage)).toEqual(["plumbing", "plumbing_elevations"]);
  });

  it("лист без темы — свой пункт", () => {
    const all = sections(sheetTabs([page(1, "01 Схема"), page(2, "02 Электрика", "electrical")]));
    expect(all.map((s) => s.key)).toEqual(["sheet:1", "electrical"]);
  });
});

describe("sectionOf", () => {
  const all = sections(full);

  it("вкладка — в своём разделе", () => {
    expect(sectionOf(all, full.find((t) => t.stage === "plumbing_elevations")!)?.key).toBe("plumbing");
    expect(sectionOf(all, full.find((t) => t.stage === "elevations")!)?.key).toBe("electrical");
    expect(sectionOf(all, null)).toBeNull();
  });
});

describe("wallLayersOf", () => {
  it("слои стены — по теме листа развёрток", () => {
    expect(wallLayersOf("plumbing_elevations")).toEqual({ electrical: false, water: true });
    expect(wallLayersOf("elevations")).toEqual({ electrical: true, water: false });
    expect(wallLayersOf("plan")).toBeNull();
    expect(wallLayersOf(undefined)).toBeNull();
  });
});

describe("placeAmongViews", () => {
  const views = ["lighting", "electrical", "low", "wiring"].map((v) => ({ key: `view:${v}`, view: v }));
  const panel = { key: "tab:5", stage: "panel" };
  const heat = { key: "tab:6", stage: "floor_heating" };

  it("тёплый пол — после «Связи», перед «Проводкой»; щит остаётся на месте", () => {
    expect(placeAmongViews([...views, panel, heat]).map((it) => it.key))
      .toEqual(["view:lighting", "view:electrical", "view:low", "tab:6", "view:wiring", "tab:5"]);
  });

  it("без вида «Проводка» вкладка стоит, где была", () => {
    const short = views.filter((v) => v.view !== "wiring");
    expect(placeAmongViews([...short, panel, heat]).map((it) => it.key))
      .toEqual(["view:lighting", "view:electrical", "view:low", "tab:5", "tab:6"]);
  });
});
