// Геометрия правки трасс: точки — [x, y] в мм модели, трассы ортогональные.
// Те же правила, что routing.simplify / move_end в ядре.

import { SNAP_MM } from "@/shared/consts";
import type { XY } from "@/shared/types";

export const snap = (v: number) => Math.round(v / SNAP_MM) * SNAP_MM;
const same = (a: number, b: number) => Math.abs(a - b) < 0.01;
export const samePt = (a: XY, b: XY) => same(a[0], b[0]) && same(a[1], b[1]);
export const isH = (a: XY, b: XY) => Math.abs(a[1] - b[1]) <= Math.abs(a[0] - b[0]);
export const clamp = (v: number, a: number, b: number) => Math.min(Math.max(v, Math.min(a, b)), Math.max(a, b));

// Без повторов и без точек на прямой
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

// Сдвиг выделенных участков: горизонталь — на dy, вертикаль — на dx; соседние участки
// удлиняются или укорачиваются, углы прямые. Концы линии пристёгнуты к коробке и точке:
// сдвинутый крайний участок получает перпендикулярный отвод от конца
export function dragPath(orig: XY[], segs: Set<number>, dx: number, dy: number): XY[] {
  const pts: XY[] = orig.map((p) => [p[0], p[1]]);
  for (const i of segs) {
    const axis = isH(orig[i], orig[i + 1]) ? 1 : 0, d = axis ? dy : dx;
    pts[i][axis] = orig[i][axis] + d;
    pts[i + 1][axis] = orig[i + 1][axis] + d;
  }
  if (segs.has(0)) pts.unshift([orig[0][0], orig[0][1]]);
  if (segs.has(orig.length - 2)) pts.push([orig[orig.length - 1][0], orig[orig.length - 1][1]]);
  return simplifyPath(pts);
}

// Конец трассы — в точку p, углы прямые
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
