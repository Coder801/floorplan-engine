import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Scene, XY } from "@/shared/types";
import { WallMap } from "./index";

const rect = (x0: number, y0: number, x1: number, y1: number): XY[] => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
const scene = {
  ceiling: 2700, assumed: { ceiling: false, openings: [] },
  floors: [{ key: "room:a", rings: [rect(0, 0, 3000, 4000)] }],
  walls: [{ key: "wall:a.w1", polys: [[rect(-100, 0, 0, 4000)]], z: [0, 2700], normals: [[1, 0]] }],
  wires: {}, points: {}, boxes: {},
} as unknown as Scene;

describe("WallMap", () => {
  it("says which wall is open and draws the flat with a figure facing it", () => {
    const { container } = render(<WallMap scene={scene} elevation="elevation:a.w1" title="Кухня — стена 1" face={[[0, 0], [0, 4000]]} />);
    expect(screen.getByRole("figure", { name: "Где стена: Кухня — стена 1" })).toHaveTextContent("Кухня — стена 1");
    expect(container.querySelectorAll("polygon").length).toBeGreaterThan(0);
    expect(container.querySelector("circle")).not.toBeNull();  // the figure's head
  });

  it("a ceiling lights the whole room, without a figure", () => {
    const { container } = render(<WallMap scene={scene} elevation="elevation:a.ceiling" title="Кухня — потолок" />);
    expect(container.querySelector("circle")).toBeNull();
  });
});
