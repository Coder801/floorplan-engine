import { describe, expect, it } from "vitest";
import { fanLayout, ROW } from "./fan";

describe("веер кабелей коробки", () => {
  it("строки по центру коробки, коробка — посередине", () => {
    const { h, cy, ys } = fanLayout(3, ROW);
    expect(h).toBe(3 * ROW);
    expect(cy).toBe(h / 2);
    expect(ys).toEqual([ROW / 2, ROW * 1.5, ROW * 2.5]);
  });
  it("один кабель или ни одного: место под коробку остаётся", () => {
    expect(fanLayout(0, ROW)).toEqual({ h: 40, cy: 20, ys: [] });
    const one = fanLayout(1, 24);
    expect(one.h).toBe(40);
    expect(one.ys).toEqual([20]);
  });
});
