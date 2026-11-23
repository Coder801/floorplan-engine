import { describe, expect, it } from "vitest";
import {
  domainOf, heldBack, placeAmongViews, sectionOf, sections, serviceOn, serviceOverview, servicePages, stageOn, wallLayersOf, wallLayersOn, withComingSoon,
} from "./domains";
import { overview } from "./testData";
import { sheetTabs } from "./tabs";
import type { ManifestPage } from "./types";

const page = (index: number, name: string, stage?: string): ManifestPage =>
  ({ index, name, stage, format: "A2", size: [594, 420], file: `pages/${index}.json` });

const PAGES = [
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
];
const full = sheetTabs(PAGES);

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

describe("withComingSoon", () => {
  const soon = (stage: string) => ({ key: `soon:${stage}`, stage });
  const panel = { key: "tab:5", stage: "panel" };

  it("тёплый пол до релиза: собранный лист заменяется неактивным пунктом", () => {
    expect(withComingSoon([{ key: "view:wiring", view: "wiring" }, panel, { key: "tab:6", stage: "floor_heating" }], "electrical", soon)
      .map((it) => it.key)).toEqual(["view:wiring", "tab:5", "soon:floor_heating"]);
  });

  it("нет листа — пункт всё равно есть; у сантехники ничего не добавляется", () => {
    expect(withComingSoon([panel], "electrical", soon).map((it) => it.key)).toEqual(["tab:5", "soon:floor_heating"]);
    expect(withComingSoon([panel], "plumbing", soon)).toEqual([panel]);
  });

  it("отложенный лист узнаётся по теме", () => {
    expect(heldBack("floor_heating")).toBe(true);
    expect(heldBack("panel")).toBe(false);
    expect(heldBack(undefined)).toBe(false);
  });
});

describe("services", () => {
  it("домен листа; виды вкладки «Электрика» — электрика, план — вне доменов", () => {
    expect(domainOf("wiring")).toBe("electrical");
    expect(domainOf("lighting")).toBe("electrical");
    expect(domainOf("floor_heating")).toBe("electrical");
    expect(domainOf("plumbing_elevations")).toBe("plumbing");
    expect(domainOf("plan")).toBeNull();
    expect(domainOf(undefined)).toBeNull();
  });

  it("нет списка (старый сервер) — включено всё", () => {
    expect(serviceOn(undefined, "plumbing")).toBe(true);
    expect(stageOn(undefined, "wiring")).toBe(true);
    expect(servicePages(PAGES, undefined)).toHaveLength(PAGES.length);
  });

  it("выключенная сантехника убирает её листы и развёртки; план и электрика остаются", () => {
    const shown = servicePages(PAGES, ["electrical"]);
    expect(shown.map((p) => p.index)).toEqual([1, 2, 3, 4, 5, 6, 8, 9]);
    expect(sections(sheetTabs(shown)).map((s) => s.key)).toEqual(["sheet:1", "electrical"]);
  });

  it("выключенная электрика убирает все её листы, включая виды «Освещение» и «Проводка»", () => {
    const shown = servicePages(PAGES, ["plumbing", "demolition"]);
    expect(shown.map((p) => p.stage)).toEqual(["plan", "plumbing", "plumbing_elevations"]);
  });

  it("без сервисов остаются только листы вне доменов; без них — пусто, без ошибок", () => {
    expect(servicePages(PAGES, []).map((p) => p.stage)).toEqual(["plan"]);
    expect(servicePages(PAGES.slice(1), [])).toEqual([]);
    expect(sections([])).toEqual([]);
  });

  it("слои стены — по сервисам", () => {
    expect(wallLayersOn(undefined)).toEqual({ electrical: true, water: true });
    expect(wallLayersOn(["electrical"])).toEqual({ electrical: true, water: false });
    expect(wallLayersOn(["plumbing"])).toEqual({ electrical: false, water: true });
  });

  it("обзор без блоков выключенных сервисов", () => {
    const plumbing = {
      fixtures: [], water: { distribution: "tee" as const, hot: null, cold_m: 1, hot_m: 1, outlets: 1, input_assumed: false },
      sewer: { pipes: [], risers: 0, bends: 0, tees: 0, errors: 0 }, weak: 0,
    };
    const panel = { scheme: "standard" as const, input: "C25", input_assumed: false, devices: 1, groups: 1, modules: 1, installed_w: 1, calculated_w: 1 };
    const o = overview({ points: [{ key: "socket", text: "Розетка", count: 3, unit: "шт" }], panel, plumbing });
    expect(serviceOverview(o, ["electrical"])).toEqual({ ...o, plumbing: undefined });
    expect(serviceOverview(o, ["electrical"])).not.toHaveProperty("plumbing");
    const water = serviceOverview(o, ["plumbing"]);
    expect(water).not.toHaveProperty("points");
    expect(water).not.toHaveProperty("panel");
    expect(water.plumbing).toBe(plumbing);
    expect(serviceOverview(o, undefined)).toEqual(o);
    expect(o.plumbing).toBe(plumbing);  // the source is not changed
  });
});
