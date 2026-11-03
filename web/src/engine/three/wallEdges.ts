// Seamless wall outline in 3D: walls are separate pieces (each has its own key, the cut lowers
// them one by one), but lines are drawn only where the wall ends. An edge of the top or bottom
// face is drawn if there is wall on one side and none on the other; a vertical only at a real
// corner (wall in 1 or 3 quarters around the vertex), not where two pieces meet in a line.

import type { XY } from "@/shared/types";

export interface WallPiece {
  polys: XY[][][];        // polygons: the first ring is the outline, the rest are holes
  z: [number, number];    // from and to by height, mm
}

const PROBE = 1.5;  // mm from the edge or vertex to the probe point

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

// Outline segments of each piece: [x1, y1, z1, x2, y2, z2, …], z from the piece bottom (0 … height)
export function wallEdges(pieces: readonly WallPiece[]): number[][] {
  // Neighbours by height: pieces that overlap this one in z (a lintel above a door and the wall next to it)
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
          // Face edge: wall on both sides is a seam between pieces and is not drawn
          const nx = (-(by - ay) / len) * PROBE, ny = ((bx - ax) / len) * PROBE;
          const mx = (ax + bx) / 2, my = (ay + by) / 2;
          if (wall(mx + nx, my + ny) !== wall(mx - nx, my - ny)) {
            out.push(ax, ay, 0, bx, by, 0, ax, ay, h, bx, by, h);
          }
          // Vertical at a vertex: a corner means wall in one or three quarters around it
          const around = [[1, 1], [-1, 1], [-1, -1], [1, -1]]
            .filter(([sx, sy]) => wall(ax + sx * PROBE, ay + sy * PROBE)).length;
          if (around === 1 || around === 3) out.push(ax, ay, 0, ax, ay, h);
        }
      }
    }
    return out;
  });
}
