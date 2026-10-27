import { describe, expect, it } from "vitest";
import type { XY } from "../types";
import { dragPath, moveEnd, segDistance, simplifyPath } from "./geometry";

const U: XY[] = [[0, 0], [0, 1000], [2000, 1000], [2000, 0]];  // П: вверх, вправо, вниз

describe("dragPath", () => {
  it("верх П вверх — стойки удлиняются", () => {
    expect(dragPath(U, new Set([1]), 0, 300)).toEqual([[0, 0], [0, 1300], [2000, 1300], [2000, 0]]);
  });
  it("верх П вниз — стойки укорачиваются", () => {
    expect(dragPath(U, new Set([1]), 0, -400)).toEqual([[0, 0], [0, 600], [2000, 600], [2000, 0]]);
  });
  it("крайний участок — перпендикулярный отвод от конца", () => {
    expect(dragPath(U, new Set([0]), 500, 0)).toEqual([[0, 0], [500, 0], [500, 1000], [2000, 1000], [2000, 0]]);
  });
  it("прямая — обход П", () => {
    expect(dragPath([[0, 0], [1000, 0]], new Set([0]), 0, 200)).toEqual([[0, 0], [0, 200], [1000, 200], [1000, 0]]);
  });
  it("углы всегда прямые", () => {
    const out = dragPath(U, new Set([0, 2]), 130, 0);
    for (let i = 0; i + 1 < out.length; i++) {
      const [a, b] = [out[i], out[i + 1]];
      expect(a[0] === b[0] || a[1] === b[1]).toBe(true);
    }
  });
});

describe("moveEnd", () => {
  it("поперёк первого участка — соседняя вершина следом", () => {
    expect(moveEnd(U, true, [200, 0])).toEqual([[200, 0], [200, 1000], [2000, 1000], [2000, 0]]);
  });
  it("один участок — излом", () => {
    expect(moveEnd([[0, 0], [1000, 0]], false, [1000, 300])).toEqual([[0, 0], [0, 300], [1000, 300]]);
  });
});

describe("simplifyPath и segDistance", () => {
  it("без повторов и точек на прямой", () => {
    expect(simplifyPath([[0, 0], [0, 0], [100, 0], [200, 0], [200, 100]])).toEqual([[0, 0], [200, 0], [200, 100]]);
  });
  it("расстояние до отрезка", () => {
    expect(segDistance([50, 10], [0, 0], [100, 0])).toBeCloseTo(10);
    expect(segDistance([150, 0], [0, 0], [100, 0])).toBeCloseTo(50);
  });
});
