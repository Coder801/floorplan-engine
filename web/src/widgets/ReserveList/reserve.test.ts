import { describe, expect, it } from "vitest";
import type { OverviewReserve } from "@/shared/types";
import { lightOnly, mostByPower, presetOf, reserveLevel, reserveOn, reservePower, toggleGroup } from "./reserve";

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

describe("быстрый выбор резерва", () => {
  const groups: OverviewReserve = {
    limit_kw: 3, limit_assumed: false,
    items: [
      { id: "QF1", purpose: "Свет", power: 200, kind: "light", on: true },
      { id: "QF2", purpose: "Розетки", power: 1000, kind: "sockets", on: false },
      { id: "QF3", purpose: "Духовка", power: 1500, kind: "heavy", on: false },
      { id: "QF4", purpose: "Розетки кухни", power: 2500, kind: "sockets", on: false },
      { id: "QF5", purpose: "Свет кухни", power: 100, kind: "light", on: false },
    ],
  };
  it("минимум — только свет", () => {
    expect(lightOnly(groups)).toEqual(["QF1", "QF5"]);
  });
  it("максимум по мощности: свет, затем розетки, затем тяжёлые, пока влезает в источник", () => {
    expect(mostByPower(groups)).toEqual(["QF1", "QF2", "QF3", "QF5"]);  // 2800 из 3000, кухня 2500 не влезла
    expect(reservePower(groups, mostByPower(groups))).toBeLessThanOrEqual(3000);
  });
  it("мощность источника неизвестна: всё, кроме тяжёлых", () => {
    expect(mostByPower({ ...groups, limit_kw: null })).toEqual(["QF1", "QF2", "QF4", "QF5"]);
  });
  it("какой пресет выбран: свой набор — вручную", () => {
    expect(presetOf(groups, ["QF1", "QF5"])).toBe("light");
    expect(presetOf(groups, mostByPower(groups))).toBe("max");
    expect(presetOf(groups, ["QF1"])).toBe("manual");
  });
});
