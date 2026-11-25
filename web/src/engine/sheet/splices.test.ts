import { describe, expect, it } from "vitest";
import type { Box, Item, ObjectCard, Page } from "@/shared/types";
import { bbox } from "./paint";
import { dotPath, spliceIcon, spliceMarks, splicePoints } from "./splices";

const card = (splice = false): ObjectCard => ({
  title: "Розетка · № 3", rows: [],
  ...(splice ? { splice: { method: "wago", deep_mm: 60, in: null, out: [], devices: 1, joints: [] } } : {}),
});
const page = (stage: string): Page => ({
  name: "Проводка", format: "A3", size: [420, 297], background: "#fff", stage, items: [],
  objects: { "point:a": card(true), "point:b": card(), "wire:w1": card(true) },
});
const placed = (o: string, l: string, box: Box, k: "s" | "f" = "s") => ({ o, l, k, box });

describe("отметки соединений", () => {
  it("только точки листа проводки с splice", () => {
    expect(splicePoints(page("wiring"))).toEqual(new Set(["point:a"]));
    expect(splicePoints(page("electrical"))).toEqual(new Set());
    expect(splicePoints({ ...page("wiring"), objects: undefined })).toEqual(new Set());
  });

  it("правый верхний угол символа по всем его частям, без подписи; линия, а не белая заливка", () => {
    const items = [
      placed("point:a", "E-SOCKET", [10, 10, 14, 14], "f"),
      placed("point:a", "E-SOCKET", [9, 11, 15, 13]),
      placed("label:a", "E-TEXT", [16, 0, 30, 6]),
      placed("point:b", "E-SOCKET", [40, 40, 44, 44]),
    ];
    const [m, ...rest] = spliceMarks(items, new Set(["point:a"]));
    expect(rest).toEqual([]);
    expect(m.key).toBe("point:a");
    expect(m.at).toEqual([15, 10]);
    expect(m.size).toBe(6);
    expect(m.item).toBe(items[1]);
  });

  it("точка без символа на листе — без отметки", () => {
    expect(spliceMarks([placed("point:a", "E-TEXT", [0, 0, 1, 1])], new Set(["point:a"]))).toEqual([]);
  });

  it("точка — многоугольник вокруг центра", () => {
    expect(bbox(dotPath([10, 20], 2, 4))).toEqual([8, 18, 12, 22]);
  });

  it("значок легенды: символ точки и точка соединения его цветом", () => {
    const sym: Item = { k: "s", c: "#d4a72c", l: "E-SOCKET", o: "point:a", w: 0.3, d: "M10 10L14 10L14 14L10 14Z" };
    const icon = spliceIcon([sym, { ...sym, o: "point:b" }], "point:a");
    expect(icon).toHaveLength(2);
    expect(icon[0]).toEqual({ k: "s", c: "#d4a72c", w: 0.3, l: "E-SOCKET", d: sym.d });
    expect(icon[1]).toMatchObject({ k: "f", c: "#d4a72c", l: "E-SOCKET" });
    const [x0, , , y1] = bbox(icon[1].d);
    expect(x0).toBeLessThan(14);
    expect(y1).toBeGreaterThan(10);
    expect(spliceIcon([sym], "point:c")).toEqual([]);
  });
});
