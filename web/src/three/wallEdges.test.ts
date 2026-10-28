import { describe, expect, it } from "vitest";
import type { XY } from "../types";
import { wallEdges, type WallPiece } from "./wallEdges";

const rect = (x0: number, y0: number, x1: number, y1: number): XY[] => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
const piece = (ring: XY[], z: [number, number] = [0, 2700]): WallPiece => ({ polys: [[ring]], z });

// Отрезки куска как [x1, y1, z1, x2, y2, z2]
const segs = (flat: number[]) => Array.from({ length: flat.length / 6 }, (_, i) => flat.slice(i * 6, i * 6 + 6));
const vertical = (s: number[]) => s[0] === s[3] && s[1] === s[4];

describe("wallEdges", () => {
  it("отдельная стена — весь контур и четыре угла", () => {
    const [e] = wallEdges([piece(rect(0, 0, 1000, 100))]);
    const all = segs(e);
    expect(all.filter(vertical)).toHaveLength(4);
    expect(all.filter((s) => !vertical(s))).toHaveLength(8);  // 4 ребра × верх и низ
  });

  it("два куска одной стены в линию — без шва между ними", () => {
    const [a, b] = wallEdges([piece(rect(0, 0, 1000, 100)), piece(rect(1000, 0, 2000, 100))]);
    for (const e of [a, b]) {
      const all = segs(e);
      // Нет рёбер и вертикалей на стыке x = 1000
      expect(all.some((s) => s[0] === 1000 && s[3] === 1000)).toBe(false);
      expect(all.filter(vertical)).toHaveLength(2);  // только внешние углы
    }
  });

  it("Г-образный стык — внутренний и внешний угол остаются, шов уходит", () => {
    const [a, b] = wallEdges([piece(rect(0, 0, 1000, 100)), piece(rect(0, 100, 100, 1000))]);
    const verticals = [...segs(a), ...segs(b)].filter(vertical).map((s) => `${s[0]},${s[1]}`);
    expect(verticals).toContain("100,100");  // внутренний угол (стена в трёх четвертях)
    expect(verticals).not.toContain("0,100");  // конец шва на прямой грани
  });

  it("перемычка над проёмом — сосед по высоте, общий шов не рисуется", () => {
    const [, lintel] = wallEdges([piece(rect(0, 0, 1000, 100)), piece(rect(1000, 0, 1800, 100), [2100, 2700])]);
    expect(segs(lintel).some((s) => s[0] === 1000 && s[3] === 1000)).toBe(false);
  });
});
