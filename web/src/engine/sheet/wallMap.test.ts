import { describe, expect, it } from "vitest";
import type { Scene, XY } from "@/shared/types";
import { ceilingGuide, CUT_SHARE, frame, hull, outerRing, standPoint, viewer, wallMap } from "./wallMap";

const rect = (x0: number, y0: number, x1: number, y1: number): XY[] => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];

const scene = (): Scene => ({
  ceiling: 2700,
  assumed: { ceiling: false, openings: [] },
  floors: [{ key: "room:a", rings: [rect(0, 0, 3000, 4000)] }, { key: "room:b", rings: [rect(3100, 0, 6000, 4000)] }],
  walls: [
    { key: "wall:a.w1", polys: [[rect(-100, 0, 0, 4000)]], z: [0, 2700], normals: [[1, 0]] },
    { key: "wall:a.w3", polys: [[rect(3000, 0, 3100, 4000)]], z: [0, 2700], normals: [[-1, 0], [1, 0]] },
    { key: "wall:a.w2", polys: [[rect(1000, 4000, 1800, 4100)]], z: [2100, 2700], normals: [[0, -1]] },  // lintel
  ],
  wires: {}, points: {}, boxes: {},
});

describe("wallMap", () => {
  it("стена развёртки — цветом, пол её помещения — подсветкой", () => {
    const faces = wallMap(scene(), "wall:a.w3", "a");
    expect(faces.filter((f) => f.kind === "room")).toHaveLength(1);
    expect(faces.filter((f) => f.kind === "floor")).toHaveLength(1);
    expect(faces.some((f) => f.kind === "litTop")).toBe(true);
    expect(faces.filter((f) => f.kind === "lit").length).toBeGreaterThan(0);
  });

  it("плита — под полами помещений, чтобы в проёмах не было фона", () => {
    const slab = [rect(-100, 0, 6000, 4100)];
    const faces = wallMap({ ...scene(), slab }, null, null);
    expect(faces[0].kind).toBe("slab");
    expect(faces.filter((f) => f.kind === "slab")).toHaveLength(1);
    expect(wallMap(scene(), null, null).some((f) => f.kind === "slab")).toBe(false);  // old build
  });

  it("полы — первыми, перемычки выше среза — не рисуются", () => {
    const faces = wallMap(scene(), null, null);
    expect(faces.slice(0, 2).every((f) => f.kind === "floor")).toBe(true);
    // Two walls with the same top; the lintel (2100…2700) is above the cut 2700 × CUT_SHARE
    expect(2100).toBeGreaterThan(2700 * CUT_SHARE);
    expect(faces.filter((f) => f.kind === "top")).toHaveLength(2);
  });

  it("видны только грани к камере: у прямоугольной стены — две боковые", () => {
    const faces = wallMap({ ...scene(), walls: [scene().walls[0]] }, null, null);
    expect(faces.filter((f) => f.kind === "left" || f.kind === "right")).toHaveLength(2);
    const [x0, y0, x1, y1] = frame(faces);
    expect(x1 > x0 && y1 > y0).toBe(true);
  });

  it("с гранью стены — взгляд человечка на полу; человечек — значком у его ног", () => {
    const face: [XY, XY] = [[3000, 4000], [3000, 0]];
    const faces = wallMap(scene(), "wall:a.w3", "a", face);
    expect(faces.filter((f) => f.kind === "view")).toHaveLength(1);
    expect(wallMap(scene(), "wall:a.w3", "a").some((f) => f.kind === "view")).toBe(false);
    const man = viewer(scene(), "a", face);
    expect(man.view.pts[0]).toEqual(man.feet);
    expect(man.size).toBe(1300);  // flat smaller than 16 m in width and depth: icon as is
  });
});

describe("standPoint", () => {
  it("перед серединой грани, внутри помещения (обход по часовой — помещение справа)", () => {
    // The right wall of a 3000 × 4000 rectangle runs down: the room is to its left on the plan
    const { at, normal } = standPoint([[3000, 4000], [3000, 0]], rect(0, 0, 3000, 4000));
    expect(normal).toEqual([-1, -0]);
    expect(at).toEqual([1900, 2000]);
  });

  it("в узком коридоре — не дальше середины", () => {
    const { at } = standPoint([[0, 0], [0, 4000]], rect(0, 0, 1000, 4000));
    expect(at[0]).toBeCloseTo(450);
    expect(at[1]).toBeCloseTo(2000);
  });
});

describe("ceilingGuide", () => {
  it("the ceiling outline is the flat outline lifted to the height, the dimension spans it", () => {
    const slab = [rect(-100, 0, 6000, 4100)];
    const low = ceilingGuide({ ...scene(), slab }, 2500)!;
    const high = ceilingGuide({ ...scene(), slab }, 3000)!;
    expect(low.outline).toHaveLength(4);
    // Higher ceiling: the outline goes up on screen by the same amount at every corner
    const lift = low.outline[0][1] - high.outline[0][1];
    expect(lift).toBeGreaterThan(0);
    low.outline.forEach((p, i) => expect(p[1] - high.outline[i][1]).toBeCloseTo(lift));
    // The dimension is vertical and as long as a post
    const [[, py0], [, py1]] = low.posts[0];
    expect(low.dim.from[0]).toBeCloseTo(low.dim.to[0]);
    expect(Math.abs(low.dim.from[1] - low.dim.to[1])).toBeCloseTo(Math.abs(py0 - py1));
    expect(low.posts.length).toBeGreaterThanOrEqual(2);
  });

  it("without a slab the outline is the hull of the room floors; nothing to draw — null", () => {
    expect(outerRing(scene())).toHaveLength(4);
    expect(ceilingGuide({ ...scene(), floors: [] }, 2700)).toBeNull();
  });

  it("walls are cut where asked", () => {
    const tops = (cut: number) => wallMap(scene(), null, null, undefined, cut).filter((f) => f.kind === "top");
    expect(tops(1000)[0].pts[0][1]).toBeGreaterThan(tops(2000)[0].pts[0][1]);  // higher cut: higher on screen
  });
});

describe("hull", () => {
  it("drops the inner points", () => {
    expect(hull([[0, 0], [2, 0], [1, 1], [2, 2], [0, 2]])).toHaveLength(4);
  });
});
