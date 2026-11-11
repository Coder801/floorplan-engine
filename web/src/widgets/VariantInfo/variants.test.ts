import { describe, expect, it } from "vitest";
import type { Variants, VariantSummary } from "@/shared/types";
import { activeSummary, availableRoutes, breakersOf, breakersOfScheme, findChoice, modeOfBreakers, neighbours, optionsOf, parseKey } from "./variants";

const item = (mode: VariantSummary["mode"], route: VariantSummary["route"], total: number): VariantSummary => ({
  key: `${mode}-${route}-boxes`, mode, route, distribution: "boxes", total, currency: "грн",
  unpriced: 0, cable_m: 10, devices: 5, chases_m: 3, conduit_m: 0, edited: false,
});

describe("варианты проводки", () => {
  it("разбирает ключ и подставляет стандарт на непонятное", () => {
    expect(parseKey("economy-floor-boxes")).toEqual({ mode: "economy", route: "floor" });
    expect(parseKey("??")).toEqual({ mode: "standard", route: "ceiling" });
  });

  it("набор из мастера: ключ с опциями, выбранный — первый в сводке", () => {
    const own = { ...item("standard", "ceiling", 120), key: "standard-ceiling-loop-shortest", distribution: "loop", path: "shortest" } as VariantSummary;
    // a neighbour with another plaster shares the key: the chosen one comes first
    const plaster = { ...own, plaster: "before", total: 90 } as VariantSummary;
    const v: Variants = { active: own.key, default: "standard-ceiling-boxes", items: [own, plaster] };
    expect(parseKey(own.key)).toEqual({ mode: "standard", route: "ceiling" });
    expect(activeSummary(v)?.total).toBe(120);
  });

  it("соседи: какой шаг отличается, в порядке шагов мастера", () => {
    const base = item("standard", "ceiling", 100);
    const v: Variants = { active: base.key, default: base.key, items: [
      base,
      { ...item("proper", "ceiling", 150), conduit: "ceiling" },  // breakers; "don't know" conduit follows
      { ...base, plaster: "before", total: 90 },
      item("standard", "floor", 110),
      { ...base, key: "standard-ceiling-loop", distribution: "loop", total: 95 },
      { ...item("standard", "floor", 1), distribution: "loop" },  // two steps: not a neighbour
    ] };
    expect(neighbours(v).map((n) => [n.step, n.value, n.summary.total])).toEqual([
      ["route", "floor", 110], ["distribution", "loop", 95], ["plaster", "before", 90], ["breakers", "lines", 150],
    ]);
    expect(neighbours({ ...v, active: "none" })).toEqual([]);
  });

  it("схема щита называется как шаг «Автоматы»", () => {
    expect(breakersOfScheme("economy")).toBe("simple");
    expect(breakersOfScheme("premium")).toBe("lines");
  });

  it("сводка точного набора; чего нет — не подставляем похожее", () => {
    const v: Variants = { active: "standard-ceiling-boxes", default: "standard-ceiling-boxes", items: [item("standard", "ceiling", 100)] };
    const base = { mode: "standard", route: "ceiling", distribution: "boxes", path: "right", conduit: "none", plaster: "after", rough_light: false } as const;
    expect(findChoice(v, base)?.total).toBe(100);
    expect(findChoice(v, { ...base, path: "shortest" })).toBeUndefined();
    expect(findChoice(v, { ...base, distribution: "loop" })).toBeUndefined();
    expect(findChoice(v, { ...base, conduit: null })?.total).toBe(100);  // "don't know": as the mode
    expect(findChoice(v, { ...base, conduit: "walls" })).toBeUndefined();
  });

  it("опции старой сборки — по режиму", () => {
    expect(optionsOf(undefined, "economy")).toEqual({ path: "shortest", conduit: "none", plaster: "after", rough_light: false });
    expect(optionsOf(undefined, "proper")).toEqual({ path: "right", conduit: "ceiling", plaster: "after", rough_light: false });
    expect(optionsOf({ ...item("standard", "ceiling", 1), conduit: true }, "standard").conduit).toBe("ceiling");  // an older build
    expect(optionsOf({ ...item("standard", "ceiling", 1), conduit: "walls" }, "standard").conduit).toBe("walls");
  });

  it("показывает только трассы, которые есть в проекте", () => {
    const ceilingOnly: Variants = { active: "standard-ceiling-boxes", default: "standard-ceiling-boxes",
      items: [item("standard", "ceiling", 100), item("economy", "ceiling", 80)] };
    expect(availableRoutes(ceilingOnly)).toEqual(["ceiling"]);
    const both: Variants = { ...ceilingOnly, items: [item("standard", "ceiling", 100), item("economy", "floor", 80)] };
    expect(availableRoutes(both)).toEqual(["ceiling", "floor"]);
    expect(availableRoutes({ ...ceilingOnly, items: [] })).toEqual(["ceiling", "floor"]);
  });
});

describe("автоматы в мастере — это режим", () => {
  it("режим и выбор переводятся туда и обратно", () => {
    for (const mode of ["economy", "standard", "proper"] as const) expect(modeOfBreakers(breakersOf(mode))).toBe(mode);
    expect(modeOfBreakers(undefined)).toBeUndefined();
  });
});
