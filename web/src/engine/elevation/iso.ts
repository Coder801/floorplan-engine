// Elevation isometry: the wall at 45° and part of the neighbouring wall at the corner, as if
// you stand in the room facing the corner. The projection is parallel, so the wall plane maps
// onto the screen affinely: the elevation is drawn by the same code in wall mm through the
// plane matrix (plane), labels in px.
//
// Space in mm: x along the elevation wall (from the left corner), y up from the floor, z from
// the wall into the room. A neighbour at a 90° corner runs from the corner towards the viewer:
// at the left corner the plane x = 0, at the right x = length. Screen in mm: X right, Y up
// (scale and offset belong to the canvas).

import type { ElevSide, Elevation, XY } from "@/shared/types";

type V3 = [number, number, number];

// Wall plane matrix: wall mm (x, y) → screen mm: X = a·x + c·y + e, Y = b·x + d·y + f
export type Mat = [number, number, number, number, number, number];

export type Corner = "left" | "right";

const LOOK_DOWN = 0.45;      // view tilt: camera rise to the horizontal (1 is a 35° isometry)
const PART = { min: 1500, share: 0.6 };  // visible part of the neighbour: at least 1.5 m, 0.6 of the wall length
const FLOOR_SHARE = 0.4;     // floor without a neighbour: a band of 0.4 wall length (no more than PART.min)

const norm = ([x, y, z]: V3): V3 => { const l = Math.hypot(x, y, z); return [x / l, y / l, z / l]; };
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

// Which corner to show: a 90° neighbour (visible together with the wall); with both, the
// left one; with none, still the left one but without a neighbour
export function isoCorner(e: Pick<Elevation, "left" | "right">): { corner: Corner; side: ElevSide | null } {
  if (e.left?.turn === 90) return { corner: "left", side: e.left };
  if (e.right?.turn === 90) return { corner: "right", side: e.right };
  return { corner: "left", side: null };
}

// Wall in isometry: its plane matrix and the visible span along its x; cut says from which
// edge the wall goes on beyond the view (the cut line is there)
export interface IsoWall { mat: Mat; from: number; to: number; height: number; cut?: "from" | "to" }

export interface IsoScene {
  corner: Corner;
  main: IsoWall;
  side: (IsoWall & { wall: ElevSide }) | null;
  floor: XY[];           // floor by the walls on screen, mm
  at(x: number, y: number, z: number): XY;
}

export function isoScene(e: Pick<Elevation, "length" | "top" | "left" | "right">): IsoScene {
  const { corner, side } = isoCorner(e);
  const L = e.length, H = e.top;
  // The camera is in front and to the side of the opposite corner, looking at the corner
  const C = norm([corner === "left" ? 1 : -1, LOOK_DOWN, 1]);
  const R = norm(cross([0, 1, 0], C));
  const U = cross(C, R);
  const at = (x: number, y: number, z: number): XY => [dot([x, y, z], R), dot([x, y, z], U)];
  // Plane: origin o, wall axis a, y is up
  const plane = (o: V3, a: V3): Mat => [dot(a, R), dot(a, U), R[1], U[1], dot(o, R), dot(o, U)];
  const main: IsoWall = { mat: plane([0, 0, 0], [1, 0, 0]), from: 0, to: L, height: H };
  let near: IsoScene["side"] = null;
  let depth = Math.min(PART.min, FLOOR_SHARE * L);
  if (side) {
    const part = Math.min(side.length, Math.max(PART.min, PART.share * L));
    depth = part;
    // The left neighbour ends at the corner (its x = length is at the corner), the right one starts at the corner
    const more = part < side.length - 1;
    near = corner === "left"
      ? { wall: side, mat: plane([0, 0, side.length], [0, 0, -1]), from: side.length - part, to: side.length, height: H,
          cut: more ? "from" : undefined }
      : { wall: side, mat: plane([L, 0, 0], [0, 0, 1]), from: 0, to: part, height: H, cut: more ? "to" : undefined };
  }
  const floor = [at(0, 0, 0), at(L, 0, 0), at(L, 0, depth), at(0, 0, depth)];
  return { corner, main, side: near, floor, at };
}

// Wall point (wall mm) on the screen, mm
export const onPlane = ([a, b, c, d, e, f]: Mat, x: number, y: number): XY => [a * x + c * y + e, b * x + d * y + f];

// Scene frame on the screen, mm: both walls at full height and the floor
export function isoBounds(s: IsoScene): [number, number, number, number] {
  const pts: XY[] = [...s.floor];
  for (const w of [s.main, s.side]) {
    if (!w) continue;
    for (const x of [w.from, w.to]) for (const y of [0, w.height]) pts.push(onPlane(w.mat, x, y));
  }
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

// Outline of the visible part of the wall in wall mm: floor, edge, ceiling, edge; the cut
// edge is a wave (amplitude amp, half wave about 350 mm)
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

// Canvas transform (a, b, c, d, e, f): x' = a·x + c·y + e, y' = b·x + d·y + f
export type Affine = [number, number, number, number, number, number];

// Flat elevation → isometry: flat wall view px (screen = o + mm·s, y up) to isometry px of the
// same wall (plane m). Through it the flat wall drawing (badges, dashes, labelled scales)
// lands on the wall plane as a whole
export function flatToIso([a, b, c, d, e, f]: Mat, s: number, ox: number, oy: number): Affine {
  return [a, -b, -c, d, ox - a * ox + c * oy + s * e, oy + b * ox - d * oy - s * f];
}

export function invert([a, b, c, d, e, f]: Affine): Affine {
  const det = a * d - b * c;
  return [d / det, -b / det, -c / det, a / det, (c * f - d * e) / det, (b * e - a * f) / det];
}

export const apply = ([a, b, c, d, e, f]: Affine, x: number, y: number): XY => [a * x + c * y + e, b * x + d * y + f];
