import { describe, expect, it } from "vitest";
import { boldLayer } from "./paint";

describe("boldLayer", () => {
  it("bolder on screen: engineering lines, not the building and furniture under them", () => {
    expect(["E-SOCKET", "W-CABLE-LIGHT", "E-FLOORHEAT", "P-COLD"].every(boldLayer)).toBe(true);
    expect(["A-WALL", "A-DIMS", "F-FURN", "0"].some(boldLayer)).toBe(false);
  });
});
