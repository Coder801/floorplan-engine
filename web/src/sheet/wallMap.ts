// Мини-схема к развёртке: квартира в изометрии «в разрезе» (стены срезаны по высоте, видно
// внутрь), стена развёртки — цветом, пол её помещения — подсветкой. Статичная картинка из
// 3D-сцены (ключ scene листа проводки): грани — многоугольниками SVG от дальних к ближним.

import type { Scene, XY } from "../types";

type V3 = [number, number, number];

export type FaceKind = "floor" | "room" | "top" | "left" | "right" | "lit" | "litTop";

export interface Face {
  kind: FaceKind;
  pts: XY[];  // на экране: x вправо, y вниз
}

export const CUT_SHARE = 0.45;  // стены — до этой доли высоты потолка

// Камера — как «Изометрия» в 3D: с юго-запада сверху (направление к камере)
const C: V3 = norm([-1, -1, 1.15]);
const RIGHT: V3 = norm([1, -1, 0]);           // ось z × на камеру
const UP: V3 = cross(C, RIGHT);

function norm([x, y, z]: V3): V3 { const l = Math.hypot(x, y, z); return [x / l, y / l, z / l]; }
function cross(a: V3, b: V3): V3 { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const screen = (p: V3): XY => [dot(p, RIGHT), -dot(p, UP)];

const area = (r: XY[]) => r.reduce((s, [x, y], i) => { const [u, v] = r[(i + 1) % r.length]; return s + x * v - u * y; }, 0) / 2;

// wall — ключ стены сцены (wall:bath.w3), room — её помещение (bath)
export function wallMap(scene: Scene, wall: string | null, room: string | null): Face[] {
  const cut = scene.ceiling * CUT_SHARE;
  const faces: { depth: number; face: Face }[] = [];
  for (const f of scene.floors) {
    const id = f.key.slice(f.key.indexOf(":") + 1);
    faces.push({ depth: -Infinity, face: { kind: id === room ? "room" : "floor", pts: f.rings[0].map(([x, y]) => screen([x, y, 0])) } });
  }
  for (const w of scene.walls) {
    if (w.z[0] >= cut) continue;  // перемычки над проёмами — выше среза
    const z0 = w.z[0], z1 = Math.min(w.z[1], cut), lit = w.key === wall;
    for (const poly of w.polys) {
      const ring = poly[0];
      const ccw = area(ring) > 0;
      const [cx, cy] = ring.reduce(([sx, sy], [x, y]) => [sx + x / ring.length, sy + y / ring.length], [0, 0]);
      const prism: Face[] = [];
      // Боковые грани, повёрнутые к камере: внешняя нормаль ребра — по обходу кольца
      for (let i = 0; i < ring.length; i++) {
        const [ax, ay] = ring[i], [bx, by] = ring[(i + 1) % ring.length];
        const n: V3 = ccw ? [by - ay, ax - bx, 0] : [ay - by, bx - ax, 0];
        if (dot(n, C) <= 1e-9) continue;
        const side = dot(n, RIGHT) > 0 ? "right" : "left";
        prism.push({ kind: lit ? "lit" : side, pts: [[ax, ay, z0], [bx, by, z0], [bx, by, z1], [ax, ay, z1]].map((p) => screen(p as V3)) });
      }
      prism.push({ kind: lit ? "litTop" : "top", pts: ring.map(([x, y]) => screen([x, y, z1])) });
      const depth = dot([cx, cy, 0], C);
      for (const face of prism) faces.push({ depth, face });
    }
  }
  // От дальних к ближним; внутри куска — бока, затем верх (порядок сохраняется)
  return faces.map((f, i) => ({ ...f, i })).sort((a, b) => a.depth - b.depth || a.i - b.i).map((f) => f.face);
}

// Рамка всех граней: [x0, y0, x1, y1] — для viewBox
export function frame(faces: readonly Face[]): [number, number, number, number] {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const f of faces) for (const [x, y] of f.pts) {
    x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
  }
  return [x0, y0, x1, y1];
}
