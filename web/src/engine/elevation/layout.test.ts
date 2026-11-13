import { describe, expect, it } from "vitest";
import { badgePlaces, leader, spread, type Rect, handleSpan } from "./layout";

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
    expect(a).toEqual({ at: [13, -14, 33, 2], far: false });
    // A second badge on the same symbol: right is taken, so left
    const [b] = badgePlaces([{ w: 20, anchor: sym }], 16, taken);
    expect(b).toEqual({ at: [-23, -3, -3, 13], far: false });
  });

  it("всё рядом занято кабелями — уходит дальше и помечается для выноски", () => {
    const sym: Rect = [0, 0, 10, 10];
    const cables: Rect[] = [[-40, -40, 50, 50]];
    const [p] = badgePlaces([{ w: 20, anchor: sym }], 16, cables);
    expect(p.far).toBe(true);
    expect(cables.slice(0, 1).some((t) => p.at[0] < t[2] && t[0] < p.at[2] && p.at[1] < t[3] && t[1] < p.at[3])).toBe(false);
    // The leader runs from the label box to the symbol centre
    expect(leader(p.at, sym).slice(2)).toEqual([5, 5]);
  });

  it("с рамками стены не выходит за них", () => {
    const sym: Rect = [0, 0, 10, 10];
    const [p] = badgePlaces([{ w: 20, anchor: sym }], 16, [], [-30, -2, 60, 40]);
    expect(p.at[1]).toBeGreaterThanOrEqual(-2);
  });
});

describe("handleSpan", () => {
  it("puts the handle on the edge away from the hinges", () => {
    expect(handleSpan(1000, 1800, "start")).toEqual([1740, 1620]);
    expect(handleSpan(1000, 1800, "end")).toEqual([1060, 1180]);
  });
});
