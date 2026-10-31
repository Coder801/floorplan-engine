import { describe, expect, it } from "vitest";
import type { ElevSide } from "@/shared/types";
import { apply, flatToIso, invert, isoBounds, isoCorner, isoScene, onPlane, wallOutline } from "./iso";

const side = (turn: number, length = 3000): ElevSide =>
  ({ key: "elevation:r.w", turn, length, openings: [], chases: [], boxes: [], points: [] });

describe("isoCorner", () => {
  it("сосед под 90° — его угол; оба — левый; ни одного — левый без соседа", () => {
    expect(isoCorner({ left: side(270), right: side(90) }).corner).toBe("right");
    expect(isoCorner({ left: side(90), right: side(90) }).corner).toBe("left");
    const none = isoCorner({ left: side(270), right: side(180) });
    expect(none).toEqual({ corner: "left", side: null });
    expect(isoCorner({}).side).toBeNull();
  });
});

describe("isoScene", () => {
  const wall = { length: 4000, top: 2700 };

  it("левый угол: стена уходит вправо, сосед — влево от угла, сходятся в углу", () => {
    const s = isoScene({ ...wall, left: side(90, 3000), right: side(90) });
    const corner = onPlane(s.main.mat, 0, 0);
    expect(onPlane(s.main.mat, 4000, 0)[0]).toBeGreaterThan(corner[0]);
    const n = s.side!;
    // Конец левого соседа — в углу; видна часть у угла
    expect(onPlane(n.mat, 3000, 0)[0]).toBeCloseTo(corner[0]);
    expect(onPlane(n.mat, 3000, 0)[1]).toBeCloseTo(corner[1]);
    expect(onPlane(n.mat, n.from, 0)[0]).toBeLessThan(corner[0]);
    expect(n.to).toBe(3000);
    expect(n.to - n.from).toBe(2400);  // 0,6 × 4000
  });

  it("правый угол: сосед начинается в правом углу и уходит вправо", () => {
    const s = isoScene({ ...wall, left: side(270), right: side(90, 1000) });
    const corner = onPlane(s.main.mat, 4000, 0);
    const n = s.side!;
    expect(onPlane(n.mat, 0, 0)[0]).toBeCloseTo(corner[0]);
    expect(onPlane(n.mat, 1000, 0)[0]).toBeGreaterThan(corner[0]);
    expect([n.from, n.to]).toEqual([0, 1000]);  // короче видимой части — целиком
  });

  it("вверх по стене — вверх по экрану; рамка охватывает стены", () => {
    const s = isoScene({ ...wall, left: side(90) });
    const [, y0] = onPlane(s.main.mat, 0, 0), [, y1] = onPlane(s.main.mat, 0, 2700);
    expect(y1).toBeGreaterThan(y0);
    const [bx0, by0, bx1, by1] = isoBounds(s);
    for (const [x, y] of [onPlane(s.main.mat, 4000, 2700), onPlane(s.side!.mat, s.side!.from, 0)]) {
      expect(x >= bx0 - 1e-6 && x <= bx1 + 1e-6 && y >= by0 - 1e-6 && y <= by1 + 1e-6).toBe(true);
    }
  });
});

describe("wallOutline", () => {
  it("сосед длиннее видимой части — обрыв волной с дальнего от угла края", () => {
    const left = isoScene({ length: 4000, top: 2700, left: side(90, 5000) }).side!;
    expect(left.cut).toBe("from");
    const right = isoScene({ length: 4000, top: 2700, left: side(270), right: side(90, 5000) }).side!;
    expect(right.cut).toBe("to");
    expect(isoScene({ length: 4000, top: 2700, left: side(90, 1000) }).side!.cut).toBeUndefined();
    const ring = wallOutline(left, 40);
    const edge = ring.filter(([, y]) => y > 0 && y < 2700);
    expect(edge.length).toBeGreaterThan(10);
    expect(Math.max(...edge.map(([x]) => Math.abs(x - left.from)))).toBeGreaterThan(30);
    expect(edge.every(([x]) => Math.abs(x - left.from) <= 40 + 1e-9)).toBe(true);
  });

  it("без обрыва — прямоугольник", () => {
    expect(wallOutline(isoScene({ length: 4000, top: 2700 }).main, 40)).toEqual([[0, 0], [4000, 0], [4000, 2700], [0, 2700]]);
  });
});

describe("flatToIso", () => {
  it("точка плоского вида стены попадает туда же, куда её мм на плоскости стены; обратное — назад", () => {
    const sc = isoScene({ length: 4000, top: 2700, left: side(90) });
    const s = 0.2, ox = 100, oy = 600;
    for (const w of [sc.main, sc.side!]) {
      const t = flatToIso(w.mat, s, ox, oy);
      for (const [x, y] of [[0, 0], [1200, 300], [w.to, 2700]]) {
        const [X, Y] = onPlane(w.mat, x, y);
        const [px, py] = apply(t, ox + x * s, oy - y * s);
        expect(px).toBeCloseTo(ox + X * s);
        expect(py).toBeCloseTo(oy - Y * s);
        const [bx, by] = apply(invert(t), px, py);
        expect(bx).toBeCloseTo(ox + x * s);
        expect(by).toBeCloseTo(oy - y * s);
      }
    }
  });
});
