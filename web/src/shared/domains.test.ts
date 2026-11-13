import { describe, expect, it } from "vitest";
import { sectionOf, sections, wallLayersOf } from "./domains";
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
  page(6, "06 Сантехника", "plumbing"),
  page(7, "07 Развёртки", "elevations"),
  page(8, "08 Развёртки (продолжение)", "elevations"),
]);

describe("sections", () => {
  it("собирает листы раздела в один пункт, развёртки — в каждый раздел", () => {
    const all = sections(full);
    expect(all.map((s) => s.key)).toEqual(["sheet:1", "electrical", "plumbing"]);
    expect(all[1].tabs.map((t) => t.stage)).toEqual(["electrical", "panel", "elevations"]);
    expect(all[2].tabs.map((t) => t.stage)).toEqual(["plumbing", "elevations"]);
  });

  it("без разделов развёртки — свой пункт", () => {
    const all = sections(sheetTabs([page(1, "01 План", "plan"), page(2, "02 Развёртки", "elevations")]));
    expect(all.map((s) => [s.key, s.domain])).toEqual([["sheet:1", false], ["sheet:2", false]]);
  });

  it("лист без темы — свой пункт", () => {
    const all = sections(sheetTabs([page(1, "01 Схема"), page(2, "02 Электрика", "electrical")]));
    expect(all.map((s) => s.key)).toEqual(["sheet:1", "electrical"]);
  });
});

describe("sectionOf", () => {
  const all = sections(full);
  const walls = full.find((t) => t.stage === "elevations")!;

  it("общая вкладка открыта в названном разделе, иначе в первом", () => {
    expect(sectionOf(all, walls, "plumbing")?.key).toBe("plumbing");
    expect(sectionOf(all, walls, null)?.key).toBe("electrical");
    expect(sectionOf(all, walls, "sheet:1")?.key).toBe("electrical");
  });

  it("своя вкладка — в своём разделе, что бы ни было названо", () => {
    expect(sectionOf(all, full.find((t) => t.stage === "panel")!, "plumbing")?.key).toBe("electrical");
    expect(sectionOf(all, null, "electrical")).toBeNull();
  });
});

describe("wallLayersOf", () => {
  it("слои стены по разделу — только когда разделов со стенами несколько", () => {
    const all = sections(full);
    expect(wallLayersOf(all, all[2])).toEqual({ electrical: false, water: true });
    expect(wallLayersOf(all, all[1])).toEqual({ electrical: true, water: false });
    expect(wallLayersOf(all, all[0])).toBeNull();
    const one = sections(full.filter((t) => t.stage !== "plumbing"));
    expect(wallLayersOf(one, one[1])).toBeNull();
  });
});
