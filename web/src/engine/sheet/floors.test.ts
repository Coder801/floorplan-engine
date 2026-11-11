import { describe, expect, it } from "vitest";
import { stepFades } from "./floors";

describe("stepFades", () => {
  it("fades a lit floor in and the rest out, dropping a faded one", () => {
    const fades = new Map<string, number>([["room:a", 1]]);
    expect(stepFades(fades, new Set(["zone:b.1"]), 90, 180)).toBe(true);
    expect(fades.get("zone:b.1")).toBeCloseTo(0.5);
    expect(fades.get("room:a")).toBeCloseTo(0.5);
    expect(stepFades(fades, new Set(["zone:b.1"]), 90, 180)).toBe(false);
    expect(fades.get("zone:b.1")).toBe(1);
    expect(fades.has("room:a")).toBe(false);
  });

  it("without motion the change is instant", () => {
    const fades = new Map<string, number>();
    expect(stepFades(fades, new Set(["room:a"]), 0, 0)).toBe(false);
    expect(fades.get("room:a")).toBe(1);
  });
});
