import { describe, expect, it } from "vitest";
import type { Variants, VariantSummary } from "@/shared/types";
import { activeSummary, availableRoutes, breakersOf, findChoice, findVariant, isCustom, modeOfBreakers, optionsOf, parseKey } from "./variants";

const item = (mode: VariantSummary["mode"], route: VariantSummary["route"], total: number): VariantSummary => ({
  key: `${mode}-${route}-boxes`, mode, route, distribution: "boxes", total, currency: "грн",
  unpriced: 0, cable_m: 10, devices: 5, chases_m: 3, conduit_m: 0, edited: false,
});

describe("варианты проводки", () => {
  it("разбирает ключ и подставляет стандарт на непонятное", () => {
    expect(parseKey("economy-floor-boxes")).toEqual({ mode: "economy", route: "floor" });
    expect(parseKey("??")).toEqual({ mode: "standard", route: "ceiling" });
  });

  it("находит сводку по режиму и трассе", () => {
    const v: Variants = { active: "standard-ceiling-boxes", default: "standard-ceiling-boxes",
      items: [item("standard", "ceiling", 100), item("economy", "floor", 80)] };
    expect(findVariant(v, "economy", "floor")?.total).toBe(80);
    expect(findVariant(v, "proper", "floor")).toBeUndefined();
  });

  it("набор из мастера: ключ с опциями, режимы ищутся мимо него", () => {
    const own = { ...item("standard", "ceiling", 120), key: "standard-ceiling-loop-shortest", distribution: "loop", path: "shortest" } as VariantSummary;
    const v: Variants = { active: own.key, default: "standard-ceiling-boxes", items: [own, item("standard", "ceiling", 100)] };
    expect(parseKey(own.key)).toEqual({ mode: "standard", route: "ceiling" });
    expect(isCustom(v)).toBe(true);
    expect(activeSummary(v)?.total).toBe(120);
    expect(findVariant(v, "standard", "ceiling")?.total).toBe(100);
    expect(isCustom({ ...v, active: "standard-ceiling-boxes" })).toBe(false);
  });

  it("сводка точного набора; чего нет — не подставляем похожее", () => {
    const v: Variants = { active: "standard-ceiling-boxes", default: "standard-ceiling-boxes", items: [item("standard", "ceiling", 100)] };
    const base = { mode: "standard", route: "ceiling", distribution: "boxes", path: "right", conduit: false, plaster: "after", rough_light: false } as const;
    expect(findChoice(v, base)?.total).toBe(100);
    expect(findChoice(v, { ...base, path: "shortest" })).toBeUndefined();
    expect(findChoice(v, { ...base, distribution: "loop" })).toBeUndefined();
  });

  it("опции старой сборки — по режиму", () => {
    expect(optionsOf(undefined, "economy")).toEqual({ path: "shortest", conduit: false, plaster: "after", rough_light: false });
    expect(optionsOf(undefined, "proper")).toEqual({ path: "right", conduit: true, plaster: "after", rough_light: false });
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
