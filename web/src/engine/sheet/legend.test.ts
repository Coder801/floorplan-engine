import { describe, expect, it } from "vitest";
import type { Item, LegendEntry, Page } from "@/shared/types";
import type { Drawing } from "./drawing";
import { legendShown, symbolBox, viewBoxOf, wiringLegend } from "./legend";

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

const entry = (key: string, l: string, d = "M0 0L10 0"): LegendEntry => ({ key, text: key, items: [{ k: "s", c: "#000", l, d }] });

describe("wiringLegend", () => {
  const electrical = { stage: "electrical", legend: [entry("socket", "E-SOCKET"), entry("switch", "E-SWITCH")] } as unknown as Page;
  const wiring = { stage: "wiring", legend: [entry("wires_light", "W-TEXT", "M0 0L6 0")] } as unknown as Page;
  const texts = { box: "Коробка", low: "Линии связи" };

  it("adds the point symbols, a box and the comms line to the colour families", () => {
    const d = { pages: [electrical, wiring], items: [
      { k: "f", c: "#000", l: "W-TEXT", d: "M0 0" },
      { k: "s", c: "#f00", l: "W-BOX", d: "M1 1L2 1L2 2" },
      { k: "s", c: "#f00", l: "W-CABLE-LOW", d: "M0 0L50 0L50 40" },
    ] } as unknown as Drawing;
    const out = wiringLegend(d, wiring, texts);
    expect(out.map((e) => e.key)).toEqual(["socket", "switch", "box", "wires_light", "wires_low"]);
    expect(out[4].items[0].d).toBe("M0 0L6 0");  // the length of the family lines
    expect(out[2].text).toBe("Коробка");
  });

  it("keeps the comms family of the sheet and adds nothing absent from the drawing", () => {
    const sheet = { ...wiring, legend: [entry("wires_low", "W-TEXT")] } as unknown as Page;
    const d = { pages: [sheet], items: [{ k: "s", c: "#f00", l: "W-CABLE-LOW", d: "M0 0L5 0" }] } as unknown as Drawing;
    expect(wiringLegend(d, sheet, texts).map((e) => e.key)).toEqual(["wires_low"]);
  });

  it("a colour family follows the lines of its system, a symbol its layer", () => {
    const own = new Set(["E-SOCKET", "W-CABLE-SOCKET-RCD", "W-TEXT"]);
    expect(legendShown(entry("wires_sockets", "W-TEXT"), own)).toBe(true);
    expect(legendShown(entry("wires_heavy", "W-TEXT"), own)).toBe(true);
    expect(legendShown(entry("wires_light", "W-TEXT"), own)).toBe(false);
    expect(legendShown(entry("socket", "E-SOCKET"), own)).toBe(true);
    expect(legendShown(entry("switch", "E-SWITCH"), own)).toBe(false);
  });
});
