import { describe, expect, it } from "vitest";
import { badgePlaces, spread, type Rect, handleSpan } from "./layout";

describe("spread", () => {
  it("близкие подписи разводятся на шаг", () => {
    expect(spread([0, 2, 30], 10, -100, 100)).toEqual([0, 10, 30]);
  });

  it("не влезли сверху — сдвигаются назад от границы", () => {
    expect(spread([90, 95], 10, 0, 100)).toEqual([90, 100]);
    expect(spread([96, 98], 10, 0, 100)).toEqual([90, 100]);
  });
});

describe("badgePlaces", () => {
  it("плашка — справа сверху от символа, занятое — обходит", () => {
    const sym: Rect = [0, 0, 10, 10];
    const taken: Rect[] = [sym];
    const [a] = badgePlaces([{ w: 20, anchor: sym }], 16, taken);
    expect(a).toEqual([13, -14, 33, 2]);
    // A second badge on the same symbol: right is taken, so left
    const [b] = badgePlaces([{ w: 20, anchor: sym }], 16, taken);
    expect(b).toEqual([-23, -3, -3, 13]);
  });
});

describe("handleSpan", () => {
  it("puts the handle on the edge away from the hinges", () => {
    expect(handleSpan(1000, 1800, "start")).toEqual([1740, 1620]);
    expect(handleSpan(1000, 1800, "end")).toEqual([1060, 1180]);
  });
});
