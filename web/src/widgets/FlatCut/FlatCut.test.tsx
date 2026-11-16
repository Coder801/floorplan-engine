import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Scene, XY } from "@/shared/types";
import { FlatCut } from "./index";

const rect = (x0: number, y0: number, x1: number, y1: number): XY[] => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
const scene = {
  ceiling: 2700, assumed: { ceiling: false, openings: [] },
  floors: [{ key: "room:a", rings: [rect(0, 0, 3000, 4000)] }],
  walls: [{ key: "wall:a.w1", polys: [[rect(-100, 0, 0, 4000)]], z: [0, 2700], normals: [[1, 0]] }],
  wires: {}, points: {}, boxes: {}, slab: [rect(-100, 0, 3000, 4000)],
} as unknown as Scene;

describe("FlatCut", () => {
  it("draws the flat cut away with the typed ceiling height", () => {
    const { container, rerender } = render(<FlatCut scene={scene} height={2650} />);
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelector("text")).toHaveTextContent("2650");
    const box = container.querySelector("svg")!.getAttribute("viewBox");
    rerender(<FlatCut scene={scene} height={3100} />);
    expect(container.querySelector("text")).toHaveTextContent("3100");
    expect(container.querySelector("svg")!.getAttribute("viewBox")).toBe(box);  // the picture does not jump
  });
});
