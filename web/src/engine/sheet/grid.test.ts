import { describe, expect, it } from "vitest";
import type { Item, Page } from "@/shared/types";
import type { Drawing } from "./drawing";
import { gridLines, gridStep, paperRings, planeRing } from "./grid";

describe("gridStep", () => {
  it("круглый шаг 1-2-5, квадрат не мельче минимума", () => {
    expect(gridStep(0.1, 12)).toBe(200);    // 120 мм нужно → 200
    expect(gridStep(0.05, 12)).toBe(500);   // 240 → 500
    expect(gridStep(0.02, 12)).toBe(1000);  // 600 → 1000
    expect(gridStep(1, 12)).toBe(20);
    expect(gridStep(0.12, 12)).toBe(100);   // ровно 100
  });
});

describe("gridLines", () => {
  it("линии по всей ширине, каждая пятая от нуля модели — главная", () => {
    const lines = gridLines(-25, 10, 40);
    expect(lines.map((l) => l.at)).toEqual([5, 15, 25, 35]);
    expect(lines.map((l) => l.major)).toEqual([false, false, true, false]);
  });
  it("ноль модели на экране — главная линия", () => {
    expect(gridLines(7, 10, 20)).toEqual([{ at: 7, major: true }, { at: 17, major: false }]);
  });
});

const page = (over: Partial<Page>) => ({ items: [], size: [100, 100], ...over }) as unknown as Page;
const drawing = (base: Page, pages: Page[]) => ({ base, pages }) as unknown as Drawing;

describe("planeRing", () => {
  const it0 = (d: string, over = {}) => ({ k: "s", c: "#000", l: "E-ELEV", d, ...over }) as Item;
  const big = "M0 0L0 10L20 10L20 0L0 0", small = "M2 2L2 8L18 8L18 2L2 2";
  it("самый большой замкнутый контур слоя развёртки", () => {
    expect(planeRing([it0(small), it0(big)])).toEqual([[0, 0], [0, 10], [20, 10], [20, 0], [0, 0]]);
  });
  it("заливки, чужие слои, незамкнутые и составные линии — не контур", () => {
    expect(planeRing([it0(big, { k: "f" }), it0(big, { l: "W-CABLE-LIGHT" }), it0("M0 0L0 10L20 10L20 0"), it0(`${big}${small}`)])).toBeNull();
  });
});

describe("paperRings", () => {
  it("лист развёрток: бумага — помещение плоскости потолка", () => {
    const outline = (o: string): Item => ({ k: "s", c: "#000", l: "E-ELEV", o, d: "M0 0L0 10L20 10L20 0L0 0" });
    const base = page({ stage: "elevations", items: [outline("elevation:bath.ceiling")] });
    expect(paperRings(drawing(base, [base]))).toEqual([[[0, 0], [0, 10], [20, 10], [20, 0], [0, 0]]]);
    const whole = page({ stage: "elevations", items: [outline("elevation:bath.ceiling"), outline("elevation:hall.ceiling")] });
    expect(paperRings(drawing(whole, [whole]))).toEqual([]);
  });
  it("плита пола из сцены — в мм листа, y перевёрнут", () => {
    const base = page({ model: [0.01, 10, 90] });
    const scene = page({ scene: { slab: [[[0, 0], [1000, 0], [1000, 2000]]] } as unknown as Page["scene"] });
    expect(paperRings(drawing(base, [base, scene]))).toEqual([[[10, 90], [20, 90], [20, 70]]]);
  });
  it("без плиты — полы помещений листа плана, сдвинутые на основной лист, без отверстий", () => {
    const base = page({ model: [0.02, 0, 100] });
    const plan = page({ model: [0.01, 10, 90], floors: { "room:a": [[[10, 90], [20, 90], [20, 70]], [[12, 88], [13, 88], [13, 87]]] } });
    expect(paperRings(drawing(base, [base, plan]))).toEqual([[[0, 100], [20, 100], [20, 60]]]);
  });
  it("нет ни плиты, ни полов — бумаги нет, сетка везде", () => {
    const base = page({});
    expect(paperRings(drawing(base, [base]))).toEqual([]);
  });
});
