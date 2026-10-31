// Контур стен в 3D без швов: стены — отдельные куски (у каждого свой ключ, «срез» опускает
// их по одному), но линии рисуются только там, где стена кончается. Ребро верхней или нижней
// грани — если по одну его сторону стена, а по другую нет; вертикаль — только в настоящем
// углу (стена в 1 или 3 четвертях вокруг вершины), а не на стыке двух кусков в одну линию.

import type { XY } from "@/shared/types";

export interface WallPiece {
  polys: XY[][][];        // многоугольники: первое кольцо — контур, остальные — отверстия
  z: [number, number];    // от и до по высоте, мм
}

const PROBE = 1.5;  // мм от ребра или вершины до пробной точки

function inRing(x: number, y: number, ring: XY[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

const inPoly = (x: number, y: number, rings: XY[][]) =>
  inRing(x, y, rings[0]) && !rings.slice(1).some((h) => inRing(x, y, h));

// Отрезки контура каждого куска: [x1, y1, z1, x2, y2, z2, …], z — от низа куска (0 … высота)
export function wallEdges(pieces: readonly WallPiece[]): number[][] {
  // Соседи по высоте: куски, что перекрываются с этим по z (перемычка над дверью и стена рядом)
  const near = pieces.map((p) => pieces.filter((q) => q.z[0] < p.z[1] && p.z[0] < q.z[1]));
  return pieces.map((p, k) => {
    const wall = (x: number, y: number) => near[k].some((q) => q.polys.some((r) => inPoly(x, y, r)));
    const h = p.z[1] - p.z[0];
    const out: number[] = [];
    for (const rings of p.polys) {
      for (const ring of rings) {
        for (let i = 0; i < ring.length; i++) {
          const [ax, ay] = ring[i], [bx, by] = ring[(i + 1) % ring.length];
          const len = Math.hypot(bx - ax, by - ay);
          if (len < 1e-6) continue;
          // Ребро граней: стена с обеих сторон — шов между кусками, не рисуется
          const nx = (-(by - ay) / len) * PROBE, ny = ((bx - ax) / len) * PROBE;
          const mx = (ax + bx) / 2, my = (ay + by) / 2;
          if (wall(mx + nx, my + ny) !== wall(mx - nx, my - ny)) {
            out.push(ax, ay, 0, bx, by, 0, ax, ay, h, bx, by, h);
          }
          // Вертикаль в вершине: угол — стена в одной или трёх четвертях вокруг
          const around = [[1, 1], [-1, 1], [-1, -1], [1, -1]]
            .filter(([sx, sy]) => wall(ax + sx * PROBE, ay + sy * PROBE)).length;
          if (around === 1 || around === 3) out.push(ax, ay, 0, ax, ay, h);
        }
      }
    }
    return out;
  });
}
