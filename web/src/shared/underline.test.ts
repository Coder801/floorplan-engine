import { describe, expect, it } from "vitest";
import { underOf } from "./underline";

describe("tab underline", () => {
  it("sits at the bottom edge of the active button, as wide as it", () => {
    expect(underOf({ offsetLeft: 120, offsetTop: 0, offsetWidth: 80, offsetHeight: 32 })).toEqual({ x: 120, y: 30, w: 80 });
  });
  it("a tab in the second row of a wrapped bar", () => {
    expect(underOf({ offsetLeft: 4, offsetTop: 36, offsetWidth: 60, offsetHeight: 32 }, 3)).toEqual({ x: 4, y: 65, w: 60 });
  });
});
