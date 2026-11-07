import { describe, expect, it } from "vitest";
import { parseCeiling } from "./ceiling";

describe("parseCeiling", () => {
  it("принимает от 2000 до 4000 мм включительно", () => {
    expect(parseCeiling("2000")).toBe(2000);
    expect(parseCeiling("4000")).toBe(4000);
    expect(parseCeiling(" 2750 ")).toBe(2750);
    expect(parseCeiling("2750,5")).toBe(2750.5);
  });
  it("отклоняет вне границ, пустое и не число", () => {
    for (const bad of ["1999", "4001", "", "  ", "abc", "2,7"]) expect(parseCeiling(bad)).toBeNull();
  });
});
