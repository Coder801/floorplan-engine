import { describe, expect, it } from "vitest";
import type { Scene, XY } from "@/shared/types";
import { CUT_SHARE, frame, standPoint, viewer, wallMap } from "./wallMap";

const rect = (x0: number, y0: number, x1: number, y1: number): XY[] => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];

const scene = (): Scene => ({
  ceiling: 2700,
  assumed: { ceiling: false, openings: [] },
  floors: [{ key: "room:a", rings: [rect(0, 0, 3000, 4000)] }, { key: "room:b", rings: [rect(3100, 0, 6000, 4000)] }],
  walls: [
    { key: "wall:a.w1", polys: [[rect(-100, 0, 0, 4000)]], z: [0, 2700], normals: [[1, 0]] },
    { key: "wall:a.w3", polys: [[rect(3000, 0, 3100, 4000)]], z: [0, 2700], normals: [[-1, 0], [1, 0]] },
    { key: "wall:a.w2", polys: [[rect(1000, 4000, 1800, 4100)]], z: [2100, 2700], normals: [[0, -1]] },  // перемычка
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

  it("полы — первыми, перемычки выше среза — не рисуются", () => {
    const faces = wallMap(scene(), null, null);
    expect(faces.slice(0, 2).every((f) => f.kind === "floor")).toBe(true);
    // Две стены по одному верху; перемычка (2100…2700) выше среза 2700 × CUT_SHARE
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
    expect(man.size).toBe(1300);  // квартира меньше 16 м по ширине и глубине — значок как есть
  });
});

describe("standPoint", () => {
  it("перед серединой грани, внутри помещения (обход по часовой — помещение справа)", () => {
    // Правая стена прямоугольника 3000 × 4000 идёт вниз: помещение — слева от неё на плане
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
