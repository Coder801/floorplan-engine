import { describe, expect, it } from "vitest";
import type { Page, Scene } from "@/shared/types";
import { lightLinks, pathLines } from "./lightLinks";

// Sheet mm = 0.01·model mm + 10 (x), 100 − 0.01·model mm (y)
const page = (items: Page["items"]) => ({ stage: "lighting", model: [0.01, 10, 100], items }) as unknown as Page;
const scene = {
  ceiling: 2700,
  points: { sw: { pos: [1000, 500, 900], inward: [0, 1], type: "switch", group: "QF1", color: "#000" } },
} as unknown as Scene;

describe("light links in 3D", () => {
  it("splits a path into polylines, joining a move to where the last one ended", () => {
    expect(pathLines("M1 2L3 4M3 4L5 6M7 8L9 10")).toEqual([[[1, 2], [3, 4], [5, 6]], [[7, 8], [9, 10]]]);
    expect(pathLines("M1 2")).toEqual([]);
  });

  it("lifts a light set under the ceiling in model mm", () => {
    const [l] = lightLinks(page([{ k: "s", c: "#0000ff", l: "E-LINK", o: "light_set:a,b", d: "M20 90L30 90" }]), scene);
    expect(l.ends).toEqual(["point:a", "point:b"]);
    expect(l.lines).toEqual([[[1000, 1000, 2660], [2000, 1000, 2660]]]);
  });

  it("drops a switch link from the ceiling to its switch and joins the nearer end", () => {
    const [l] = lightLinks(page([{ k: "s", c: "#0000ff", l: "E-LINK", o: "switch_link:sw", d: "M40 90L20 90" }]), scene);
    expect(l.lines[0]).toEqual([[1000, 500, 900], [1000, 500, 2660], [1000, 1000, 2660]]);
    expect(l.lines).toHaveLength(2);
  });

  it("keeps only links, and nothing without the sheet model", () => {
    const items = [{ k: "s" as const, c: "#000", l: "E-LIGHT", o: "point:a", d: "M0 0L1 1" }];
    expect(lightLinks(page(items), scene)).toEqual([]);
    expect(lightLinks(undefined, scene)).toEqual([]);
  });
});
