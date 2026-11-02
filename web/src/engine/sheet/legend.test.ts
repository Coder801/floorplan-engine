import { describe, expect, it } from "vitest";
import type { Item } from "@/shared/types";
import { symbolBox, viewBoxOf } from "./legend";

const item = (d: string): Item => ({ k: "s", c: "#000000", l: "E-SOCKET", d });

describe("symbolBox", () => {
  it("объединяет габариты примитивов с полем", () => {
    const b = symbolBox([item("M10 20L14 20"), item("M12 18L12 22")], 0.5);
    expect(b).toEqual([9.5, 17.5, 14.5, 22.5]);
    expect(viewBoxOf(b)).toBe("9.5 17.5 5 5");
  });

  it("без примитивов — единичная рамка", () => {
    expect(symbolBox([])).toEqual([0, 0, 1, 1]);
  });
});
