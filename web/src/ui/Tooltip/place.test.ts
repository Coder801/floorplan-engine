import { describe, expect, it } from "vitest";
import { below } from "./place";

describe("место подсказки кнопки", () => {
  it("под кнопкой, по её центру", () => {
    expect(below({ left: 400, right: 500, top: 100, bottom: 130 }, 1000, 800)).toEqual({ left: 320, top: 138 });
  });
  it("над кнопкой у нижнего края экрана", () => {
    expect(below({ left: 400, right: 500, top: 750, bottom: 780 }, 1000, 800)).toEqual({ left: 320, bottom: 58 });
  });
  it("не уходит за края экрана", () => {
    expect(below({ left: 0, right: 40, top: 10, bottom: 40 }, 1000, 800).left).toBe(8);
    expect(below({ left: 960, right: 1000, top: 10, bottom: 40 }, 1000, 800).left).toBe(732);
  });
});
