import { describe, expect, it } from "vitest";
import type { Elevation } from "@/shared/types";
import { wallRows } from "./rows";

const labels = {
  from: (f: string) => `от ${f}`, box: "Коробка", board: "Щит",
  kind: { cold: "Холодная вода", hot: "Горячая вода", sewer: "Канализация" },
};
const colors = { cold: "#1f77b4", hot: "#d62728", sewer: "#8c564b" };

const wall = {
  points: [{ id: "p1", key: "point:p1", n: 3, type: "socket", name: "Розетка", x: 400, y: 300,
             posts: 1, group: "QF4", color: "#123456", from: "К1" }],
  boxes: [], board: undefined,
  water: [
    { fixture: "s", key: "fixture:s", name: "Умывальник", n: 2, kind: "sewer", x: 1000, y: 500, d: 50, assumed: true },
    { fixture: "s", key: "fixture:s", name: "Умывальник", n: 2, kind: "cold", x: 1075, y: 550, d: 16, assumed: false },
    { fixture: "w", key: "fixture:w", name: "Унитаз", n: 1, kind: "cold", x: 300, y: 200, d: 16, assumed: false },
  ],
} as unknown as Elevation;

describe("wallRows", () => {
  it("электрика и вода — отдельно", () => {
    const { electrical, water } = wallRows(wall, labels, colors);
    expect(electrical.map((r) => r.mark)).toEqual(["3"]);
    expect(electrical[0].line).toBe("QF4 · от К1");
    expect(water.map((r) => r.name)).toEqual(["Унитаз", "Умывальник", "Умывальник"]);
  });

  it("вода: по номеру прибора, холодная раньше канализации; ключ строки — свой у подвода", () => {
    const { water } = wallRows(wall, labels, colors);
    expect(water.map((r) => r.line)).toEqual(["Холодная вода · Ø16", "Холодная вода · Ø16", "Канализация · Ø50"]);
    expect(water[2]).toMatchObject({ mark: "2*", color: "#8c564b", key: "fixture:s", where: "1000 × 500" });
    expect(new Set(water.map((r) => r.id)).size).toBe(3);
  });

  it("стена без воды — раздел воды пустой", () => {
    expect(wallRows({ ...wall, water: undefined }, labels, colors).water).toEqual([]);
  });
});
