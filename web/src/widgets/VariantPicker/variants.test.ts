import { describe, expect, it } from "vitest";
import type { Variants, VariantSummary } from "@/shared/types";
import { availableRoutes, findVariant, parseKey } from "./variants";

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

  it("показывает только трассы, которые есть в проекте", () => {
    const ceilingOnly: Variants = { active: "standard-ceiling-boxes", default: "standard-ceiling-boxes",
      items: [item("standard", "ceiling", 100), item("economy", "ceiling", 80)] };
    expect(availableRoutes(ceilingOnly)).toEqual(["ceiling"]);
    const both: Variants = { ...ceilingOnly, items: [item("standard", "ceiling", 100), item("economy", "floor", 80)] };
    expect(availableRoutes(both)).toEqual(["ceiling", "floor"]);
    expect(availableRoutes({ ...ceilingOnly, items: [] })).toEqual(["ceiling", "floor"]);
  });
});
