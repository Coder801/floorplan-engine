import { describe, expect, it } from "vitest";
import type { Item } from "@/shared/types";
import type { Box } from "@/shared/types";
import type { Page } from "@/shared/types";
import { boldLayer, boxWithin, cardFrames, isBackdrop, isTint, partInView, strokeWidth } from "./paint";

describe("boldLayer", () => {
  it("bolder on screen: engineering lines, not the building and furniture under them", () => {
    expect(["E-SOCKET", "W-CABLE-LIGHT", "E-FLOORHEAT", "P-COLD"].every(boldLayer)).toBe(true);
    expect(["A-WALL", "A-DIMS", "F-FURN", "0"].some(boldLayer)).toBe(false);
  });
});

describe("strokeWidth", () => {
  const line = (l: string, w?: number): Item => ({ k: "s", c: "#000000", l, d: "M0 0L1 1", w });
  it("bolder engineering lines, the building as on the sheet", () => {
    expect(strokeWidth(line("E-SOCKET", 0.25), 1, 1.6, 0, 0, 0)).toBeCloseTo(0.4);
    expect(strokeWidth(line("A-WALL", 0.25), 1, 1.6, 0, 0, 0)).toBeCloseTo(0.25);
  });
  it("never thinner than the floor of its kind", () => {
    expect(strokeWidth(line("E-LIGHT", 0.25), 1, 1.6, 0.1, 0.6, 0.5)).toBeCloseTo(0.5);
    expect(strokeWidth(line("W-CABLE-LIGHT", 0.25), 1, 1.6, 0.1, 0.6, 0.5)).toBeCloseTo(0.6);
    expect(strokeWidth(line("A-WALL", 0.25), 1, 1.6, 0.3, 0.6, 0.5)).toBeCloseTo(0.3);
  });
  it("in PNG (bold 1, no floors) the width of the sheet", () => {
    expect(strokeWidth(line("E-SOCKET", 0.25), 1, 1, 0, 0, 0)).toBeCloseTo(0.25);
  });
});

describe("isBackdrop", () => {
  const item = (k: "f" | "s", c: string): Item => ({ k, c, l: "W-CABLE-QF1", d: "M0 0L1 0", o: "wire:w1" });
  it("a white fill is the background under a label: the highlight does not cover the text with it", () => {
    expect(isBackdrop(item("f", "#ffffff"))).toBe(true);
    expect(isBackdrop(item("f", "#FFFFFFcc"))).toBe(true);
  });
  it("lines and coloured fills are the object itself", () => {
    expect(isBackdrop(item("s", "#ffffff"))).toBe(false);
    expect(isBackdrop(item("f", "#f28e2b"))).toBe(false);
  });
});

describe("isTint", () => {
  const fill = (c: string, k: "f" | "s" = "f"): Item => ({ k, c, l: "E-FLOORHEAT-ZONE", d: "M0 0L1 0", o: "heating:z1" });
  it("a see-through fill is a tinted area: lit, it stays see-through", () => {
    expect(isTint(fill("#ff993326"))).toBe(true);
  });
  it("opaque fills and lines are not", () => {
    expect(isTint(fill("#ff9933"))).toBe(false);
    expect(isTint(fill("#ff9933ff"))).toBe(false);
    expect(isTint(fill("#ff993326", "s"))).toBe(false);
  });
});

describe("cardFrames", () => {
  const at = (k: "f" | "s", c: string, box: Box, o = "heating:z1") => ({ k, c, l: "E-FLOORHEAT-TEXT", d: "M0 0", o, box });
  it("a line round its object's white backdrop is a card frame: lit, it is not thickened over the text", () => {
    const back = at("f", "#ffffff", [10, 10, 40, 22]);
    const frame = at("s", "#d32f2f", [10, 10, 40.1, 22]);
    const zone = at("s", "#808080", [0, 0, 100, 80]);
    const other = at("s", "#d32f2f", [10, 10, 40, 22], "heating:z2");
    expect(cardFrames([back, frame, zone, other])).toEqual(new Set([frame]));
  });
});

describe("partInView", () => {
  const page = { view: [100, 100, 300, 300], size: [420, 297] } as unknown as Page;
  it("text of the tables and legend round the viewport is not in it, though its box spans the sheet", () => {
    expect(partInView(page, "M10 10L20 10L20 20ZM350 280L360 280L360 290Z")).toBe(false);
  });
  it("a part inside, or the whole path inside, is in the viewport", () => {
    expect(partInView(page, "M10 10L20 10L20 20ZM150 150L160 150L160 160Z")).toBe(true);
    expect(partInView(page, "M150 150L160 160")).toBe(true);
  });
  it("a path away from the viewport is not in it", () => {
    expect(partInView(page, "M310 10L320 20")).toBe(false);
  });
});

describe("boxWithin", () => {
  it("inside with a tolerance", () => {
    expect(boxWithin([10, 10, 20, 20], [9.8, 10, 20.2, 20])).toBe(true);
    expect(boxWithin([10, 10, 21, 20], [10, 10, 20, 20])).toBe(false);
  });
});
