import { describe, expect, it } from "vitest";
import type { OverviewReserve } from "@/shared/types";
import { reserveLevel, reserveOn, reservePower, toggleGroup } from "./reserve";

const r: OverviewReserve = {
  limit_kw: 5, limit_assumed: true,
  items: [
    { id: "QF1", purpose: "Свет", power: 400, on: true },
    { id: "QF2", purpose: "Розетки", power: 2000, on: false },
    { id: "QF3", purpose: "Кухня", power: 1500, on: true },
  ],
};

describe("группы резерва", () => {
  it("начальный выбор и сумма", () => {
    expect(reserveOn(r)).toEqual(["QF1", "QF3"]);
    expect(reservePower(r, ["QF1", "QF3"])).toBe(1900);
  });
  it("уровень: норма, близко к лимиту с 80 %, перегруз только выше лимита", () => {
    expect(reserveLevel(3999, 5)).toBe("ok");
    expect(reserveLevel(4000, 5)).toBe("near");
    expect(reserveLevel(5000, 5)).toBe("near");
    expect(reserveLevel(5001, 5)).toBe("over");
    expect(reserveLevel(99000, null)).toBe("ok");
  });
  it("порядок — как на щите, что бы ни нажимали", () => {
    expect(toggleGroup(r, ["QF3"], "QF1")).toEqual(["QF1", "QF3"]);
    expect(toggleGroup(r, ["QF1", "QF3"], "QF1")).toEqual(["QF3"]);
  });
});
