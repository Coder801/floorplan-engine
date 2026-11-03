// Route edit geometry: points are [x, y] in model mm. Routes are orthogonal, but economy may
// have slanted pieces too (routing.any_angle): such a piece moves parallel to itself.
// The same rules as routing.simplify / move_end in the core.

import { SNAP_MM } from "@/shared/consts";
import type { XY } from "@/shared/types";

export const snap = (v: number) => Math.round(v / SNAP_MM) * SNAP_MM;
const same = (a: number, b: number) => Math.abs(a - b) < 0.01;
export const samePt = (a: XY, b: XY) => same(a[0], b[0]) && same(a[1], b[1]);
export const isH = (a: XY, b: XY) => Math.abs(a[1] - b[1]) <= Math.abs(a[0] - b[0]);
// Piece along an axis (with a tolerance, like ORTHO in the core)
export const isAxis = (a: XY, b: XY) => Math.abs(a[0] - b[0]) <= 0.5 || Math.abs(a[1] - b[1]) <= 0.5;
export const clamp = (v: number, a: number, b: number) => Math.min(Math.max(v, Math.min(a, b)), Math.max(a, b));

// No duplicates and no collinear points
export function simplifyPath(path: XY[]): XY[] {
  let out = path;
  for (let pass = 0; pass < 4; pass++) {
    const next: XY[] = [];
    for (const p of out) {
      const b = next[next.length - 1], a = next[next.length - 2];
      if (b && samePt(p, b)) continue;
      if (a && ((same(a[0], b[0]) && same(b[0], p[0])) || (same(a[1], b[1]) && same(b[1], p[1])))) {
        next[next.length - 1] = p;
        continue;
      }
      next.push(p);
    }
    if (next.length === out.length) return next;
    out = next;
  }
  return out;
}

// Moving selected pieces: a horizontal one by dy, a vertical one by dx, a slanted one (economy)
// parallel to itself by the projection of the shift onto its normal; the neighbouring pieces
// get longer or shorter. Line ends are pinned to the box and the point: a moved end piece
// gets a stub from the end
export function dragPath(orig: XY[], segs: Set<number>, dx: number, dy: number): XY[] {
  const pts: XY[] = orig.map((p) => [p[0], p[1]]);
  for (const i of segs) {
    const a = orig[i], b = orig[i + 1];
    if (!isAxis(a, b)) {
      const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
      const nx = -(b[1] - a[1]) / len, ny = (b[0] - a[0]) / len, d = dx * nx + dy * ny;
      pts[i] = [a[0] + nx * d, a[1] + ny * d];
      pts[i + 1] = [b[0] + nx * d, b[1] + ny * d];
      continue;
    }
    const axis = isH(a, b) ? 1 : 0, d = axis ? dy : dx;
    pts[i][axis] = a[axis] + d;
    pts[i + 1][axis] = b[axis] + d;
  }
  if (segs.has(0)) pts.unshift([orig[0][0], orig[0][1]]);
  if (segs.has(orig.length - 2)) pts.push([orig[orig.length - 1][0], orig[orig.length - 1][1]]);
  return simplifyPath(pts);
}

// Move the route end to point p, keeping right angles
export function moveEnd(path: XY[], atStart: boolean, p: XY): XY[] {
  let pts: XY[] = (atStart ? path : [...path].reverse()).map((q) => [q[0], q[1]]);
  const [a, b] = pts;
  const bend: XY = isH(a, b) ? [b[0], p[1]] : [p[0], b[1]];
  if (pts.length >= 3) { pts[0] = [p[0], p[1]]; pts[1] = bend; }
  else pts = [[p[0], p[1]], bend, b];
  pts = simplifyPath(pts);
  return atStart ? pts : pts.reverse();
}

export function segDistance(p: XY, a: XY, b: XY): number {
  const vx = b[0] - a[0], vy = b[1] - a[1], len = vx * vx + vy * vy;
  const t = len ? clamp(((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / len, 0, 1) : 0;
  return Math.hypot(p[0] - a[0] - t * vx, p[1] - a[1] - t * vy);
}
