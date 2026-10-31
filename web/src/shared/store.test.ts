import { describe, expect, it } from "vitest";
import { shown3d } from "./store";

describe("shown3d", () => {
  const all = { groups: null, room: null };
  it("без фильтра видно всё, и без группы тоже", () => {
    expect(shown3d(all, "QF1", "kitchen")).toBe(true);
    expect(shown3d(all, null, undefined)).toBe(true);
  });
  it("группы: только отмеченные, без группы — скрыто", () => {
    const f = { groups: new Set(["QF2"]), room: null };
    expect(shown3d(f, "QF2", "hall")).toBe(true);
    expect(shown3d(f, "QF3", "hall")).toBe(false);
    expect(shown3d(f, null, "hall")).toBe(false);
  });
  it("помещение и группы вместе", () => {
    const f = { groups: new Set(["QF2"]), room: "hall" };
    expect(shown3d(f, "QF2", "hall")).toBe(true);
    expect(shown3d(f, "QF2", "kitchen")).toBe(false);
    expect(shown3d({ groups: null, room: "hall" }, "QF9", undefined)).toBe(false);
  });
});
