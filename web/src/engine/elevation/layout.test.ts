import { describe, expect, it } from "vitest";
import { badgePlaces, spread, type Rect } from "./layout";

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
    // Вторая плашка у того же символа: справа занято — слева
    const [b] = badgePlaces([{ w: 20, anchor: sym }], 16, taken);
    expect(b).toEqual([-23, -3, -3, 13]);
  });
});
