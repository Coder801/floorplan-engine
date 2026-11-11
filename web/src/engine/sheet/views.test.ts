import { describe, expect, it } from "vitest";
import type { Page, SideTable } from "@/shared/types";
import type { Drawing } from "./drawing";
import { linkEnds, objectVisible, ownLayers, repeatsNumbers, systemOf, viewLayers, viewOfLayer, viewTables } from "./views";

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

  it("lighting: lights, switches, LED and their lines, no sockets or low voltage", () => {
    const v = viewLayers(own, all, "light");
    for (const l of ["A-WALL", "E-LIGHT", "E-SWITCH", "E-LED", "E-BOARD", "W-BOX", "W-CABLE-LIGHT"]) expect(v.has(l)).toBe(true);
    for (const l of ["E-SOCKET", "E-DATA", "W-CABLE-SOCKET", "W-CABLE-DEVICE", "W-CABLE-LOW"]) expect(v.has(l)).toBe(false);
  });

  it("a layer belongs to its system; walls, boxes and labels to none", () => {
    expect(["E-LIGHT", "E-LINK", "W-CABLE-LIGHT-RCD-FLOOR"].map(systemOf)).toEqual(["light", "light", "light"]);
    expect(["E-SOCKET", "W-CABLE-SOCKET-RCD", "W-CABLE-DEVICE"].map(systemOf)).toEqual(["sockets", "sockets", "sockets"]);
    expect(["E-DATA", "W-CABLE-LOW"].map(systemOf)).toEqual(["low", "low"]);
    expect(["A-WALL", "W-BOX", "W-TEXT", "E-BOARD"].map(systemOf)).toEqual([null, null, null, null]);
  });

  it("the wiring sheet without a system switched off: its points and lines are gone", () => {
    const wiring = { stage: "wiring" } as Page;
    const layers = new Set(["A-WALL", "E-LIGHT", "E-SOCKET", "E-DATA", "W-BOX", "W-TEXT", "W-CABLE-LIGHT", "W-CABLE-SOCKET", "W-CABLE-LOW"]);
    const d = { own: new Map([[wiring, layers]]), items: [] } as unknown as Drawing;
    const v = ownLayers(d, wiring, "sockets", true, new Set(["light", "low"]))!;
    expect([...v].sort()).toEqual(["A-WALL", "E-SOCKET", "W-BOX", "W-CABLE-SOCKET", "W-TEXT"]);
    // the simple mode on top: no labels either
    expect(ownLayers(d, wiring, "sockets", false, new Set(["light"]))!.has("W-TEXT")).toBe(false);
  });

  it("without cables (simple interface mode): points only, no lines, boxes or their labels", () => {
    const v = viewLayers(new Set([...own, "W-BOX"]), all, "sockets", false);
    expect(v.has("E-SOCKET") && v.has("E-BOARD") && v.has("A-WALL")).toBe(true);
    for (const l of ["W-BOX", "W-TEXT", "W-CABLE-SOCKET", "W-CABLE-DEVICE"]) expect(v.has(l)).toBe(false);
  });

  it("the wiring sheet in the simple mode: lines and boxes, no labels", () => {
    const wiring = { stage: "wiring" } as Page, plan = { stage: "plan" } as Page;
    const layers = new Set(["A-WALL", "E-SOCKET", "W-BOX", "W-TEXT", "W-CABLE-SOCKET", "W-CABLE-LIGHT"]);
    const d = { own: new Map([[wiring, layers], [plan, layers]]), items: [] } as unknown as Drawing;
    const brief = ownLayers(d, wiring, "sockets", false)!;
    for (const l of ["A-WALL", "E-SOCKET", "W-BOX", "W-CABLE-SOCKET", "W-CABLE-LIGHT"]) expect(brief.has(l)).toBe(true);
    expect(brief.has("W-TEXT")).toBe(false);
    expect(ownLayers(d, wiring, "sockets", true)).toBe(layers);
    expect([...ownLayers(d, plan, "sockets", false)!]).toEqual(["A-WALL", "E-SOCKET"]);  // other sheets: no wiring at all
  });

  it("a light link knows its points: a switch link its switch, a light set its lights", () => {
    expect(linkEnds("switch_link:sw1")).toEqual(["point:sw1"]);
    expect(linkEnds("light_set:a,b")).toEqual(["point:a", "point:b"]);
    expect(linkEnds("point:a")).toBeNull();
    expect(linkEnds(undefined)).toBeNull();
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
    expect(viewOfLayer("E-LIGHT")).toBe("light");
    expect(viewOfLayer("W-CABLE-LIGHT")).toBe("light");
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

  it("drops a group row of a switched-off system, though its box stays", () => {
    const table = { title: "Группы", columns: [], align: [], rows: [
      { cells: ["QF1"], keys: ["point:l", "wire:a", "box:1"] }, { cells: ["QF2"], keys: ["point:s", "wire:b", "box:1"] },
      { cells: ["щит"], keys: ["board:board"] },
    ] } as unknown as SideTable;
    const layerOf = new Map([["point:l", "E-LIGHT"], ["wire:a", "W-CABLE-LIGHT"], ["box:1", "W-BOX"],
                             ["point:s", "E-SOCKET"], ["wire:b", "W-CABLE-SOCKET"], ["board:board", "E-BOARD"]]);
    const [t] = viewTables([table], new Set(["E-SOCKET", "W-CABLE-SOCKET", "W-BOX", "E-BOARD"]), layerOf);
    expect(t.rows.map((r) => r.cells[0])).toEqual(["QF2", "щит"]);
  });
});
