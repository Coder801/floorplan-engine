// Shapes of the scene's objects on a wall and on the ceiling
import * as THREE from "three";
import type { XY } from "@/shared/types";

const SOCKET_TYPES = new Set(["socket", "data", "tv"]);

// Flat against a wall, a disc on the ceiling
export const flat = (inward: XY, w: number, d: number, h: number) =>
  (Math.abs(inward[0]) > Math.abs(inward[1]) ? new THREE.BoxGeometry(d, w, h) : new THREE.BoxGeometry(w, d, h));
export const disc = () => new THREE.CylinderGeometry(60, 60, 20, 24).rotateX(Math.PI / 2);

// A round plate on a wall: the axis looks into the room
export const puck = (inward: XY, r: number, d: number, segments: number) =>
  new THREE.CylinderGeometry(r, r, d, segments).rotateZ(Math.abs(inward[0]) > Math.abs(inward[1]) ? Math.PI / 2 : 0);

// Sockets are round, like the real ones; the rest of the wall points stay square plates
export const pointGeometry = (type: string, inward: XY | null) => {
  if (!inward) return disc();
  return SOCKET_TYPES.has(type) ? puck(inward, 40, 25, 24) : flat(inward, 80, 25, 80);
};
