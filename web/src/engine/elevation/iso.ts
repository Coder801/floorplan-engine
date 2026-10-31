// Изометрия развёртки: стена под 45° и часть соседней стены в углу — как стоишь в помещении
// лицом к углу. Проекция параллельная, поэтому плоскость стены ложится на экран аффинно:
// развёртку рисуют тем же кодом в мм стены через матрицу плоскости (plane), подписи — в px.
//
// Пространство — мм: x вдоль стены развёртки (от левого угла), y вверх от пола, z от стены в
// помещение. Сосед в углу 90° идёт от угла к зрителю: у левого угла — плоскость x = 0, у
// правого — x = длина. Экран — мм: X вправо, Y вверх (масштаб и сдвиг — у холста).

import type { ElevSide, Elevation, XY } from "@/shared/types";

type V3 = [number, number, number];

// Матрица плоскости стены: мм стены (x, y) → мм экрана: X = a·x + c·y + e, Y = b·x + d·y + f
export type Mat = [number, number, number, number, number, number];

export type Corner = "left" | "right";

const LOOK_DOWN = 0.45;      // наклон взгляда: подъём камеры к горизонтали (1 — изометрия 35°)
const PART = { min: 1500, share: 0.6 };  // видимая часть соседа: не меньше 1,5 м, 0,6 длины стены
const FLOOR_SHARE = 0.4;     // пол без соседа — полоса в 0,4 длины стены (не больше PART.min)

const norm = ([x, y, z]: V3): V3 => { const l = Math.hypot(x, y, z); return [x / l, y / l, z / l]; };
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

// Какой угол показывать: сосед под 90° (видна вместе со стеной); оба — левый; ни одного —
// всё равно левый, но без соседа
export function isoCorner(e: Pick<Elevation, "left" | "right">): { corner: Corner; side: ElevSide | null } {
  if (e.left?.turn === 90) return { corner: "left", side: e.left };
  if (e.right?.turn === 90) return { corner: "right", side: e.right };
  return { corner: "left", side: null };
}

// Стена в изометрии: матрица её плоскости и видимый отрезок по её x; cut — с какого края
// стена идёт дальше, чем видно (там — линия обрыва)
export interface IsoWall { mat: Mat; from: number; to: number; height: number; cut?: "from" | "to" }

export interface IsoScene {
  corner: Corner;
  main: IsoWall;
  side: (IsoWall & { wall: ElevSide }) | null;
  floor: XY[];           // пол у стен — на экране, мм
  at(x: number, y: number, z: number): XY;
}

export function isoScene(e: Pick<Elevation, "length" | "top" | "left" | "right">): IsoScene {
  const { corner, side } = isoCorner(e);
  const L = e.length, H = e.top;
  // Камера — спереди и сбоку от противоположного угла, смотрит на угол
  const C = norm([corner === "left" ? 1 : -1, LOOK_DOWN, 1]);
  const R = norm(cross([0, 1, 0], C));
  const U = cross(C, R);
  const at = (x: number, y: number, z: number): XY => [dot([x, y, z], R), dot([x, y, z], U)];
  // Плоскость: начало o, ось стены a, вверх — y
  const plane = (o: V3, a: V3): Mat => [dot(a, R), dot(a, U), R[1], U[1], dot(o, R), dot(o, U)];
  const main: IsoWall = { mat: plane([0, 0, 0], [1, 0, 0]), from: 0, to: L, height: H };
  let near: IsoScene["side"] = null;
  let depth = Math.min(PART.min, FLOOR_SHARE * L);
  if (side) {
    const part = Math.min(side.length, Math.max(PART.min, PART.share * L));
    depth = part;
    // Левый сосед кончается в углу (его x = длина — у угла), правый — начинается в углу
    const more = part < side.length - 1;
    near = corner === "left"
      ? { wall: side, mat: plane([0, 0, side.length], [0, 0, -1]), from: side.length - part, to: side.length, height: H,
          cut: more ? "from" : undefined }
      : { wall: side, mat: plane([L, 0, 0], [0, 0, 1]), from: 0, to: part, height: H, cut: more ? "to" : undefined };
  }
  const floor = [at(0, 0, 0), at(L, 0, 0), at(L, 0, depth), at(0, 0, depth)];
  return { corner, main, side: near, floor, at };
}

// Точка стены (мм стены) — на экране, мм
export const onPlane = ([a, b, c, d, e, f]: Mat, x: number, y: number): XY => [a * x + c * y + e, b * x + d * y + f];

// Рамка сцены на экране, мм: обе стены целиком по высоте и пол
export function isoBounds(s: IsoScene): [number, number, number, number] {
  const pts: XY[] = [...s.floor];
  for (const w of [s.main, s.side]) {
    if (!w) continue;
    for (const x of [w.from, w.to]) for (const y of [0, w.height]) pts.push(onPlane(w.mat, x, y));
  }
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

// Контур видимой части стены в мм стены: пол, край, потолок, край; на крае cut — волна
// обрыва (амплитуда amp, полуволна — около 350 мм)
export function wallOutline(w: IsoWall, amp: number): XY[] {
  const H = w.height, n = Math.max(2, Math.round(H / 700)), steps = n * 12;
  const wave = (x: number, y0: number, y1: number): XY[] =>
    Array.from({ length: steps - 1 }, (_, k): XY => {
      const t = (k + 1) / steps;
      return [x + amp * Math.sin(t * n * 2 * Math.PI), y0 + (y1 - y0) * t];
    });
  return [
    [w.from, 0], [w.to, 0],
    ...(w.cut === "to" ? wave(w.to, 0, H) : []),
    [w.to, H], [w.from, H],
    ...(w.cut === "from" ? wave(w.from, H, 0) : []),
  ];
}

// Преобразование canvas (a, b, c, d, e, f): x' = a·x + c·y + e, y' = b·x + d·y + f
export type Affine = [number, number, number, number, number, number];

// Плоская развёртка → изометрия: px плоского вида стены (экран = o + мм·s, y вверх) — в px
// изометрии той же стены (плоскость m). Через него плоский рисунок стены — плашки, пунктиры,
// шкалы с подписями — ложится на плоскость стены целиком
export function flatToIso([a, b, c, d, e, f]: Mat, s: number, ox: number, oy: number): Affine {
  return [a, -b, -c, d, ox - a * ox + c * oy + s * e, oy + b * ox - d * oy - s * f];
}

export function invert([a, b, c, d, e, f]: Affine): Affine {
  const det = a * d - b * c;
  return [d / det, -b / det, -c / det, a / det, (c * f - d * e) / det, (b * e - a * f) / det];
}

export const apply = ([a, b, c, d, e, f]: Affine, x: number, y: number): XY => [a * x + c * y + e, b * x + d * y + f];
