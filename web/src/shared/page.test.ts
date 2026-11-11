import { describe, expect, it } from "vitest";
import { briefCard, filteredKeys, inRings, PageIndex, rowPicked, rowSelection } from "./page";
import type { Page, XY } from "./types";

const square = (a: number, b: number): XY[] => [[a, a], [b, a], [b, b], [a, b], [a, a]];

describe("выделение строкой таблицы", () => {
  const chains = { "point:a": ["wire:w1", "box:b", "point:a"] };
  it("объекты строки с их линиями целиком", () => {
    expect(rowSelection(null, ["point:a", "point:c"], chains)).toEqual(new Set(["point:a", "wire:w1", "box:b", "point:c"]));
  });
  it("повторный клик снимает выделение, другая строка — заменяет", () => {
    const picked = rowSelection(null, ["point:a"], chains);
    expect(rowSelection(picked, ["point:a"], chains)).toBeNull();
    expect(rowSelection(picked, ["point:c"], chains)).toEqual(new Set(["point:c"]));
  });
  it("трасса на листе подсвечивает строку своей группы, чужие — нет", () => {
    const route = new Set(["wire:w1", "box:b", "point:a"]);
    expect(rowPicked(route, ["point:a", "point:x", "wire:w1", "wire:w9"])).toBe(true);
    expect(rowPicked(route, ["point:y", "wire:w2"])).toBe(false);
    expect(rowPicked(null, ["point:a"])).toBe(false);
    expect(rowPicked(route, undefined)).toBe(false);
  });
});

describe("скрытые группы", () => {
  const groups = { QF1: ["wire:w1", "point:a"], QF2: ["box:b"] };
  it("объекты скрытых групп; без фильтра и на листе без групп — ничего", () => {
    expect(filteredKeys(groups, new Set(["QF2"]))).toEqual(new Set(["wire:w1", "point:a"]));
    expect(filteredKeys(groups, null).size).toBe(0);
    expect(filteredKeys(undefined, new Set()).size).toBe(0);
  });
});

describe("wall areas", () => {
  it("counts a point inside the outer ring and outside a hole", () => {
    const rings = [square(0, 10), square(4, 6)];
    expect(inRings(rings, 2, 2)).toBe(true);
    expect(inRings(rings, 5, 5)).toBe(false);
    expect(inRings(rings, 12, 5)).toBe(false);
  });

  it("finds the wall under a point between hatch strokes", () => {
    const page = { areas: { "wall:a.w1": [square(0, 10)] }, objects: { "wall:a.w1": { title: "", rows: [] } } };
    const index = new PageIndex(page as unknown as Page);
    expect(index.areaAt(5, 5)).toBe("wall:a.w1");
    expect(index.areaAt(20, 5)).toBeNull();
  });

  it("has no areas on a sheet without the key", () => {
    expect(new PageIndex({} as Page).areaAt(5, 5)).toBeNull();
  });
});

describe("what is selected on a sheet", () => {
  const other = {
    "wall:a.w1": { title: "", rows: [] }, "opening:d": { title: "", rows: [] },
    "room:a": { title: "", rows: [] }, "dimension:a.w1": { title: "", rows: [] },
    "wire:w1": { title: "", rows: [] },
  };
  const onStage = (stage: string) =>
    new PageIndex({ stage, objects: { "point:p": { title: "", rows: [] } } } as unknown as Page, other);

  it.each(["electrical", "lighting", "wiring"])("%s: electrics only, the building is a backdrop", (stage) => {
    const index = onStage(stage);
    for (const o of ["wall:a.w1", "opening:d", "room:a", "dimension:a.w1"]) expect(index.interactive(o)).toBe(false);
    expect(index.interactive("point:p")).toBe(true);
    expect(index.interactive("wire:w1")).toBe(true);  // a layer of another electrics sheet
  });

  it("keeps the building selectable on other sheets", () => {
    expect(onStage("plumbing").interactive("wall:a.w1")).toBe(true);
    expect(onStage("plan").interactive("dimension:a.w1")).toBe(true);
  });
});

describe("card of the simple mode", () => {
  const rows: [string, string][] = [["Автомат (группа)", "QF1"], ["Кабель", "3x1.5"]];
  it("a line shows its short card", () => {
    const brief = { title: "ЩР → К1", rows: [["Трасса", "по потолку"]] as [string, string][] };
    expect(briefCard("wire:w1", { title: "QF1: ЩР → К1", rows, brief })).toBe(brief);
  });
  it("a line of an old build: the title only", () => {
    expect(briefCard("box:b1", { title: "Коробка К1", rows })).toEqual({ title: "Коробка К1", rows: [] });
  });
  it("other objects keep their card", () => {
    const card = { title: "Розетка", rows };
    expect(briefCard("point:s1", card)).toBe(card);
  });
});
