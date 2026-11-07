import { describe, expect, it } from "vitest";
import { place } from "./place";

describe("место подсказки", () => {
  it("слева от курсора, снизу в верхней половине", () => {
    expect(place({ x: 900, y: 100 }, 1000, 800)).toEqual({ right: 112, top: 112 });
  });
  it("над курсором в нижней половине", () => {
    expect(place({ x: 900, y: 700 }, 1000, 800)).toEqual({ right: 112, bottom: 112 });
  });
  it("не уходит за край узкого экрана", () => {
    expect(place({ x: 40, y: 100 }, 360, 800).right).toBe(72);
    expect(place({ x: 40, y: 100 }, 280, 800).right).toBe(8);
  });
});
