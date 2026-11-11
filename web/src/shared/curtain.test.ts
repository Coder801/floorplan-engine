import { describe, expect, it } from "vitest";
import { CURTAIN_HOLD_MS, holdLeft } from "./curtain";

describe("holdLeft", () => {
  it("keeps the mark on screen for the minimum after a fast load", () => {
    expect(holdLeft(1000, 1050)).toBe(CURTAIN_HOLD_MS - 50);
  });
  it("lifts at once after a slow load", () => {
    expect(holdLeft(1000, 1000 + CURTAIN_HOLD_MS + 300)).toBe(0);
  });
});
