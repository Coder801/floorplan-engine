import { describe, expect, it } from "vitest";
import type { Item, Page } from "@/shared/types";
import { buildDrawing, drawingLayers, layerShown, objectLayers, shiftOf } from "./drawing";

const item = (l: string, d: string, o?: string): Item => ({ k: "s", c: "#000000", l, d, o });

// Лист 100×100 с видовым экраном 10…90; model — сдвиг модели на листе
const page = (name: string, tx: number, items: Item[], extra: Partial<Page> = {}): Page => ({
  name, format: "A4", size: [100, 100], background: "#ffffff", items,
  view: [10 + tx, 10, 90 + tx, 90], model: [0.02, tx, 100], ...extra,
});

describe("shiftOf", () => {
  it("переводит лист на лист через общую модель", () => {
    const a = page("a", 0, []), b = page("b", 30, []);
    expect(shiftOf(b, a)).toEqual({ f: 1, dx: -30, dy: 0 });
    expect(shiftOf(a, a)).toEqual({ f: 1, dx: 0, dy: 0 });
  });

  it("учитывает разный масштаб листов", () => {
    const a = page("a", 0, [], { model: [0.02, 0, 100] });
    const b = page("b", 0, [], { model: [0.01, 10, 50] });
    const s = shiftOf(b, a);
    // точка модели (1000, 1000): на b — (20, 40), на a — (20, 80)
    expect(s.f * 20 + s.dx).toBeCloseTo(20);
    expect(s.f * 40 + s.dy).toBeCloseTo(80);
  });
});

describe("buildDrawing", () => {
  const plan = page("plan", 0, [
    item("A-WALL", "M20 20L80 20"), item("A-DIMS", "M20 15L80 15", "dimension:w1"),
    item("A-SHEET", "M0 0L100 0"), item("A-TEXT", "M95 95L99 99"),  // рамка и текст вне вида
  ], { objects: { "dimension:w1": { title: "Размер", rows: [] } } });
  const elec = page("electrical", 30, [
    item("A-WALL", "M50 20L110 20"), item("E-SOCKET", "M60 30L62 30", "point:s1"),
  ], { objects: { "point:s1": { title: "Розетка", rows: [] } } });
  const d = buildDrawing([plan, elec]);

  it("берёт слой с первого листа, где он есть, и не повторяет копии", () => {
    expect(d.items.map((i) => i.l)).toEqual(["A-WALL", "A-DIMS", "E-SOCKET"]);
  });

  it("переносит примитивы чужого листа на base", () => {
    const socket = d.items.find((i) => i.l === "E-SOCKET")!;
    expect(socket.box).toEqual([30, 30, 32, 30]);
    expect(d.view).toEqual([10, 10, 90, 90]);
  });

  it("помнит свои слои каждого листа — набор вкладки", () => {
    expect([...d.own.get(plan)!].sort()).toEqual(["A-DIMS", "A-WALL"]);
    expect([...d.own.get(elec)!].sort()).toEqual(["A-WALL", "E-SOCKET"]);
    expect([...drawingLayers(d).keys()]).toEqual(["A-WALL", "A-DIMS", "E-SOCKET"]);
  });

  it("собирает карточки всех листов", () => {
    expect(Object.keys(d.objects).sort()).toEqual(["dimension:w1", "point:s1"]);
  });

  it("линии размеров из слоя 0 — в слое размеров", () => {
    const one = buildDrawing([page("p", 0, [item("0", "M20 15L80 15", "dimension:w1"), item("0", "M20 20L30 20")])]);
    expect(one.items.map((i) => i.l)).toEqual(["A-DIMS", "0"]);
  });

  it("лист без model — чертёж из одного листа", () => {
    const panel = page("panel", 0, [item("E-PANEL", "M20 20L30 30")], { model: undefined });
    const one = buildDrawing([panel, elec]);
    expect(one.pages).toEqual([panel]);
  });
});

describe("objectLayers", () => {
  it("слой объекта — первый не текстовый: 3D прячет объект вместе с ним", () => {
    const d = buildDrawing([page("p", 0, [
      item("E-TEXT", "M20 20L22 20", "point:s1"), item("E-SOCKET", "M20 30L22 30", "point:s1"),
      item("W-CABLE", "M20 40L60 40", "wire:w1"),
    ])]);
    expect(Object.fromEntries(objectLayers(d))).toEqual({ "point:s1": "E-SOCKET", "wire:w1": "W-CABLE" });
  });
});

describe("layerShown", () => {
  const own = new Set(["A-WALL"]);
  it("свой слой виден, пока не выключен; чужой — если включён", () => {
    expect(layerShown(own, new Set(), new Set(), "A-WALL")).toBe(true);
    expect(layerShown(own, new Set(["A-WALL"]), new Set(), "A-WALL")).toBe(false);
    expect(layerShown(own, new Set(), new Set(), "A-DIMS")).toBe(false);
    expect(layerShown(own, new Set(), new Set(["A-DIMS"]), "A-DIMS")).toBe(true);
  });
});
