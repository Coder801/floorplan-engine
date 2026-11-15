import { describe, expect, it } from "vitest";
import type { Item } from "@/shared/types";
import { boldLayer, strokeWidth } from "./paint";

describe("boldLayer", () => {
  it("bolder on screen: engineering lines, not the building and furniture under them", () => {
    expect(["E-SOCKET", "W-CABLE-LIGHT", "E-FLOORHEAT", "P-COLD"].every(boldLayer)).toBe(true);
    expect(["A-WALL", "A-DIMS", "F-FURN", "0"].some(boldLayer)).toBe(false);
  });
});

describe("strokeWidth", () => {
  const line = (l: string, w?: number): Item => ({ k: "s", c: "#000000", l, d: "M0 0L1 1", w });
  it("bolder engineering lines, the building as on the sheet", () => {
    expect(strokeWidth(line("E-SOCKET", 0.25), 1, 1.6, 0, 0, 0)).toBeCloseTo(0.4);
    expect(strokeWidth(line("A-WALL", 0.25), 1, 1.6, 0, 0, 0)).toBeCloseTo(0.25);
  });
  it("never thinner than the floor of its kind", () => {
    expect(strokeWidth(line("E-LIGHT", 0.25), 1, 1.6, 0.1, 0.6, 0.5)).toBeCloseTo(0.5);
    expect(strokeWidth(line("W-CABLE-LIGHT", 0.25), 1, 1.6, 0.1, 0.6, 0.5)).toBeCloseTo(0.6);
    expect(strokeWidth(line("A-WALL", 0.25), 1, 1.6, 0.3, 0.6, 0.5)).toBeCloseTo(0.3);
  });
  it("in PNG (bold 1, no floors) the width of the sheet", () => {
    expect(strokeWidth(line("E-SOCKET", 0.25), 1, 1, 0, 0, 0)).toBeCloseTo(0.25);
  });
});
