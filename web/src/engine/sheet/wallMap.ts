// Mini map for an elevation: the flat in a "cut-away" isometry (walls cut down in height so
// you can see inside), the elevation wall in colour, its room's floor highlighted; in front of
// the wall a little figure faces it, with its line of sight on the floor: which side we look
// from. A static picture from the 3D scene (key scene of the wiring sheet): faces as SVG
// polygons from far to near.

import type { RoomKind, Scene, XY } from "@/shared/types";

type V3 = [number, number, number];

export type FaceKind = "slab" | "floor" | "room" | "top" | "left" | "right" | "lit" | "litTop" | "view";

export interface Face {
  kind: FaceKind;
  pts: XY[];  // on screen: x right, y down
  room?: RoomKind;  // a floor: its room kind, for a tint (the wizard picture)
}

export const CUT_SHARE = 0.45;  // walls up to this fraction of the ceiling height
const MAN = { h: 1300, stand: 1100 };  // figure icon: height and where it stands in front of the wall, mm
const MAN_SPAN = 16000;  // a larger plan (width + depth, mm) makes the figure this many times larger

// Camera like "Isometry" in 3D: from the south-west, above (direction to the camera)
const C: V3 = norm([-1, -1, 1.15]);
const RIGHT: V3 = norm([1, -1, 0]);           // z axis × towards the camera
const UP: V3 = cross(C, RIGHT);

function norm([x, y, z]: V3): V3 { const l = Math.hypot(x, y, z); return [x / l, y / l, z / l]; }
function cross(a: V3, b: V3): V3 { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const screen = (p: V3): XY => [dot(p, RIGHT), -dot(p, UP)];

const area = (r: XY[]) => r.reduce((s, [x, y], i) => { const [u, v] = r[(i + 1) % r.length]; return s + x * v - u * y; }, 0) / 2;

// wall is the scene wall key (wall:bath.w3), room its room (bath), face the inner wall face on
// the plan (start at the left corner, view from inside): the figure stands in front of it; cut —
// where walls are cut, mm (a share of the ceiling by default); whole — the room's ceiling page
// (decision 2026-11-12): its floor and all its walls are lit, not one wall
export function wallMap(scene: Scene, wall: string | null, room: string | null, face?: readonly [XY, XY],
                        cut = scene.ceiling * CUT_SHARE, whole = false): Face[] {
  const faces: { depth: number; face: Face }[] = [];
  // The slab first: door openings and pockets between walls are floor too
  for (const ring of scene.slab ?? []) {
    faces.push({ depth: -Infinity, face: { kind: "slab", pts: ring.map(([x, y]) => screen([x, y, 0])) } });
  }
  for (const f of scene.floors) {
    const id = f.key.slice(f.key.indexOf(":") + 1);
    const kind: FaceKind = id !== room ? "floor" : whole ? "lit" : "room";
    faces.push({ depth: -Infinity, face: { kind, pts: f.rings[0].map(([x, y]) => screen([x, y, 0])), ...(f.kind ? { room: f.kind } : {}) } });
  }
  for (const w of scene.walls) {
    if (w.z[0] >= cut) continue;  // lintels above openings are above the cut
    const z0 = w.z[0], z1 = Math.min(w.z[1], cut);
    const lit = w.key === wall || (whole && room !== null && w.key.startsWith(`wall:${room}.`));
    for (const poly of w.polys) {
      const ring = poly[0];
      const ccw = area(ring) > 0;
      const [cx, cy] = ring.reduce(([sx, sy], [x, y]) => [sx + x / ring.length, sy + y / ring.length], [0, 0]);
      const prism: Face[] = [];
      // Side faces turned to the camera: the outer edge normal follows the ring direction
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
  // The figure's line of sight: a wedge on the floor to the ends of the face; after floors, under walls
  const man = face ? viewer(scene, room, face) : null;
  if (man) faces.push({ depth: -Infinity, face: man.view });
  // From far to near; within a piece, sides then top (order is kept)
  return faces.map((f, i) => ({ ...f, i })).sort((a, b) => a.depth - b.depth || a.i - b.i).map((f) => f.face);
}

// Bounding box of all faces: [x0, y0, x1, y1], for viewBox
export function frame(faces: readonly Face[]): [number, number, number, number] {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const f of faces) for (const [x, y] of f.pts) {
    x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
  }
  return [x0, y0, x1, y1];
}

// Where to stand to see the wall: from the face middle into the room by MAN.stand, but no
// farther than 0.45 of the room depth along this normal (a narrow hallway)
export function standPoint([a, b]: readonly [XY, XY], ring?: readonly XY[]): { at: XY; normal: XY } {
  const dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1;
  const normal: XY = [dy / len, -dx / len];  // clockwise walk: the room is on the right
  const mid: XY = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  let depth = Infinity;
  for (const [i, p] of (ring ?? []).entries()) {
    const q = ring![(i + 1) % ring!.length];
    const ex = q[0] - p[0], ey = q[1] - p[1];
    const den = normal[0] * ey - normal[1] * ex;
    if (Math.abs(den) < 1e-9) continue;
    const t = ((p[0] - mid[0]) * ey - (p[1] - mid[1]) * ex) / den;   // along the normal
    const u = ((p[0] - mid[0]) * normal[1] - (p[1] - mid[1]) * normal[0]) / den;  // along the edge
    if (t > 1 && u >= 0 && u <= 1) depth = Math.min(depth, t);
  }
  const d = Math.min(MAN.stand, 0.45 * depth);
  return { at: [mid[0] + normal[0] * d, mid[1] + normal[1] * d], normal };
}

// The figure in front of the wall (WallMap draws it as an icon over the map): where its feet
// are on screen, the icon height and the line of sight. An icon, not a scaled figure: it is
// larger for a large flat
export function viewer(scene: Scene, room: string | null, face: readonly [XY, XY]): { feet: XY; size: number; view: Face } {
  const ring = scene.floors.find((f) => f.key === `room:${room}`)?.rings[0];
  const all = scene.floors.flatMap((f) => f.rings[0]);
  const span = all.length ? Math.max(...all.map((p) => p[0])) - Math.min(...all.map((p) => p[0])) +
                            Math.max(...all.map((p) => p[1])) - Math.min(...all.map((p) => p[1])) : 0;
  const { at: [x, y] } = standPoint(face, ring);
  const [a, b] = face;
  return {
    feet: screen([x, y, 0]),
    size: MAN.h * Math.max(1, span / MAN_SPAN),
    view: { kind: "view", pts: [screen([x, y, 0]), screen([a[0], a[1], 0]), screen([b[0], b[1], 0])] },
  };
}

// The ceiling over a cut-away flat (the setup wizard, ceiling height step): the outline of the
// flat at that height, vertical edges at its outer corners (left, right and the nearest on
// screen) and a dimension line from the floor to the ceiling at the left corner. Screen
// coordinates, as the faces of wallMap
export interface CeilingGuide {
  outline: XY[];
  posts: [XY, XY][];
  dim: { from: XY; to: XY; label: XY };
}

export function ceilingGuide(scene: Scene, height: number): CeilingGuide | null {
  const ring = outerRing(scene);
  if (ring.length < 3) return null;
  const at = (p: XY, z: number) => screen([p[0], p[1], z]);
  const ground = ring.map((p) => at(p, 0));
  const pick = (score: (q: XY) => number) => ring[ground.reduce((best, q, i) => (score(q) > score(ground[best]) ? i : best), 0)];
  const left = pick(([x]) => -x), right = pick(([x]) => x), near = pick(([, y]) => y);
  const corners = [left, right, near].filter((p, i, all) => all.indexOf(p) === i);
  const xs = ground.map(([x]) => x);
  const off = (Math.max(...xs) - Math.min(...xs)) * 0.06;  // the dimension line stands off the corner
  const [fx, fy] = at(left, 0), [tx, ty] = at(left, height);
  return {
    outline: ring.map((p) => at(p, height)),
    posts: corners.map((p) => [at(p, 0), at(p, height)]),
    dim: { from: [fx - off, fy], to: [tx - off, ty], label: [fx - off * 1.4, (fy + ty) / 2] },
  };
}

// The flat outline on the plan: the largest slab ring, or (an older build without the slab) the
// convex hull of the room floors
export function outerRing(scene: Scene): XY[] {
  const slab = [...(scene.slab ?? [])].sort((a, b) => Math.abs(area(b)) - Math.abs(area(a)))[0];
  if (slab && slab.length >= 3) return slab;
  return hull(scene.floors.flatMap((f) => f.rings[0] ?? []));
}

// Convex hull (monotone chain)
export function hull(points: readonly XY[]): XY[] {
  const pts = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (pts.length < 3) return pts;
  const turn = (o: XY, a: XY, b: XY) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const half = (list: XY[]) => {
    const out: XY[] = [];
    for (const p of list) {
      while (out.length >= 2 && turn(out[out.length - 2], out[out.length - 1], p) <= 0) out.pop();
      out.push(p);
    }
    return out.slice(0, -1);
  };
  return [...half(pts), ...half([...pts].reverse())];
}
