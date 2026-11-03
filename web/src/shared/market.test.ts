import { describe, expect, it } from "vitest";
import { deviation, monthText, periodText, place } from "./market";

describe("рынок цен", () => {
  it("период: год, месяц, диапазон", () => {
    expect(monthText("2026", "uk")).toBe("2026");
    expect(monthText("2026-11", "en")).toBe("November 2026");
    expect(periodText({ start: "2024", end: "2026-11", dated: 6, undated: 5 }, "en")).toBe("2024 – November 2026");
    expect(periodText({ start: "2026-03", end: "2026-03", dated: 1, undated: 0 }, "en")).toBe("March 2026");
    expect(periodText({ start: "", end: "", dated: 0, undated: 2 }, "en")).toBe("");
  });

  it("отклонение от медианы и место в вилке", () => {
    expect(deviation(200, 100)).toBe(100);
    expect(deviation(85, 100)).toBe(-15);
    expect(deviation(null, 100)).toBeNull();
    expect(deviation(100, undefined)).toBeNull();
    const s = { min: 10, q1: 20, q3: 40, max: 80 };
    expect([5, 15, 30, 50, 90].map((p) => place(p, s))).toEqual(["below", "low", "mid", "high", "above"]);
  });
});
