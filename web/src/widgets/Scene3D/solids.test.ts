import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { pointGeometry } from "./solids";

const size = (geo: THREE.BufferGeometry) => {
  geo.computeBoundingBox();
  const s = new THREE.Vector3();
  geo.boundingBox!.getSize(s);
  return s.toArray().map((v) => Math.round(v));
};

describe("pointGeometry", () => {
  it.each(["socket", "data", "tv"])("%s — круг на стене, ось смотрит в комнату", (type) => {
    expect(pointGeometry(type, [1, 0]).type).toBe("CylinderGeometry");
    expect(size(pointGeometry(type, [1, 0]))).toEqual([25, 80, 80]);
    expect(size(pointGeometry(type, [0, -1]))).toEqual([80, 25, 80]);
  });

  it("выключатель и вывод остаются квадратными", () => {
    expect(pointGeometry("switch", [1, 0]).type).toBe("BoxGeometry");
    expect(pointGeometry("outlet", [0, 1]).type).toBe("BoxGeometry");
  });

  it("на потолке — диск", () => {
    expect(size(pointGeometry("light", null))).toEqual([120, 120, 20]);
  });
});
