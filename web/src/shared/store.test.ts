import { describe, expect, it } from "vitest";
import { shown3d, toggledGroups } from "./store";

describe("глазик группы", () => {
  const all = ["QF1", "QF2", "QF3"];
  it("скрывает одну, остальные видны", () => {
    expect(toggledGroups(null, all, "QF2")).toEqual(new Set(["QF1", "QF3"]));
  });
  it("вернули последнюю скрытую — фильтра нет", () => {
    expect(toggledGroups(new Set(["QF1", "QF3"]), all, "QF2")).toBeNull();
  });
  it("группа без строки в таблице не пропадает при первом нажатии", () => {
    expect(toggledGroups(null, ["QF1", "QF2", "low"], "QF1")?.has("low")).toBe(true);
  });
});

describe("shown3d", () => {
  const all = { groups: null, room: null };
  it("без фильтра видно всё, и без группы тоже", () => {
    expect(shown3d(all, "QF1", "kitchen")).toBe(true);
    expect(shown3d(all, null, undefined)).toBe(true);
  });
  it("группы: только отмеченные; без группы (трубы, приборы) фильтр не трогает", () => {
    const f = { groups: new Set(["QF2"]), room: null };
    expect(shown3d(f, "QF2", "hall")).toBe(true);
    expect(shown3d(f, "QF3", "hall")).toBe(false);
    expect(shown3d(f, null, "hall")).toBe(true);
  });
  it("помещение и группы вместе", () => {
    const f = { groups: new Set(["QF2"]), room: "hall" };
    expect(shown3d(f, "QF2", "hall")).toBe(true);
    expect(shown3d(f, "QF2", "kitchen")).toBe(false);
    expect(shown3d({ groups: null, room: "hall" }, "QF9", undefined)).toBe(false);
  });
});
