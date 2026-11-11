import { describe, expect, it } from "vitest";
import { fitBox } from "./thumb";

describe("fitBox", () => {
  it("fits a wide wall by width and centres it vertically", () => {
    const { k, ox, oy } = fitBox([100, 50, 300, 100], 240, 150, 10);
    expect(k).toBeCloseTo(1.1);  // (240 - 20) / 200
    expect(100 * k + ox).toBeCloseTo(10);
    expect(300 * k + ox).toBeCloseTo(230);
    expect((50 * k + oy + 100 * k + oy) / 2).toBeCloseTo(75);
  });

  it("fits a tall wall by height", () => {
    const { k, oy } = fitBox([0, 0, 50, 260], 240, 150, 10);
    expect(k).toBeCloseTo(0.5);  // (150 - 20) / 260
    expect(oy).toBeCloseTo(10);
  });

  it("does not blow up on an empty box", () => {
    const { k } = fitBox([5, 5, 5, 5], 240, 150);
    expect(Number.isFinite(k)).toBe(true);
  });
});
