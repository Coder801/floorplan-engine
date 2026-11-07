import { describe, expect, it } from "vitest";
import type { Page, SideTable } from "@/shared/types";
import { objectVisible, repeatsNumbers, viewLayers, viewOfLayer, viewTables } from "./views";

const own = new Set(["A-WALL", "E-SOCKET", "E-SWITCH", "E-LIGHT", "E-LED", "E-DATA", "E-BOARD", "E-TEXT"]);
const all = [...own, "W-BOX", "W-TEXT", "W-CABLE-LIGHT", "W-CABLE-SOCKET", "W-CABLE-SOCKET-RCD", "W-CABLE-DEVICE", "W-CABLE-LOW"];

describe("views of the electrical tab", () => {
  it("sockets: sockets, devices and their lines, no light or low voltage", () => {
    const v = viewLayers(own, all, "sockets");
    for (const l of ["A-WALL", "E-SOCKET", "E-BOARD", "W-BOX", "W-CABLE-SOCKET", "W-CABLE-SOCKET-RCD", "W-CABLE-DEVICE"]) expect(v.has(l)).toBe(true);
    for (const l of ["E-LIGHT", "E-SWITCH", "E-LED", "E-DATA", "W-CABLE-LIGHT", "W-CABLE-LOW"]) expect(v.has(l)).toBe(false);
  });

  it("low voltage: its points and lines only", () => {
    const v = viewLayers(own, all, "low");
    expect(v.has("E-DATA") && v.has("W-CABLE-LOW") && v.has("E-BOARD")).toBe(true);
    for (const l of ["E-SOCKET", "E-LIGHT", "W-BOX", "W-CABLE-SOCKET"]) expect(v.has(l)).toBe(false);
  });

  it("a label and a box follow their object", () => {
    const layerOf = new Map([
      ["point:s", "E-SOCKET"], ["point:l", "E-LIGHT"], ["wire:a", "W-CABLE-LIGHT"], ["wire:b", "W-CABLE-SOCKET"],
    ]);
    const shown = (l: string) => l === "E-SOCKET" || l === "W-CABLE-SOCKET";
    const chains = { "box:1": ["wire:a", "point:l"], "box:2": ["wire:a", "wire:b"] };
    expect(objectVisible("label:s,l", shown, layerOf, chains)).toBe(true);
    expect(objectVisible("label:l", shown, layerOf, chains)).toBe(false);
    expect(objectVisible("box:1", shown, layerOf, chains)).toBe(false);
    expect(objectVisible("box:2", shown, layerOf, chains)).toBe(true);  // a shared box stays
    expect(objectVisible("board:board", shown, layerOf, chains)).toBe(true);
  });

  it("lighting keeps its own numbers, not the labels of the electrical sheet", () => {
    const lighting = { stage: "lighting" } as Page, electrical = { stage: "electrical" } as Page;
    expect(repeatsNumbers(lighting, { l: "E-TEXT", o: "label:a,b" })).toBe(true);
    expect(repeatsNumbers(lighting, { l: "E-TEXT", o: "led_strip:s" })).toBe(false);
    expect(repeatsNumbers(lighting, { l: "L-TEXT", o: "point:a" })).toBe(false);
    expect(repeatsNumbers(electrical, { l: "E-TEXT", o: "label:a" })).toBe(false);
  });

  it("finds the view of an object", () => {
    expect(viewOfLayer("E-LIGHT")).toBe("lighting");
    expect(viewOfLayer("E-DATA")).toBe("low");
    expect(viewOfLayer("E-SOCKET")).toBe("sockets");
    expect(viewOfLayer(undefined)).toBe("sockets");
  });

  it("keeps the table rows of the view", () => {
    const table = { title: "Точки", columns: [], align: [], rows: [
      { cells: ["1"], keys: ["point:s"] }, { cells: ["2"], keys: ["point:l"] }, { cells: ["3"] },
    ] } as unknown as SideTable;
    const layerOf = new Map([["point:s", "E-SOCKET"], ["point:l", "E-LIGHT"]]);
    const [t] = viewTables([table], new Set(["E-SOCKET"]), layerOf);
    expect(t.rows.map((r) => r.cells[0])).toEqual(["1", "3"]);
  });
});
