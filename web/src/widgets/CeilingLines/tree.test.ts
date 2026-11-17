import { describe, expect, it } from "vitest";
import type { CeilingLine } from "@/shared/types";
import { cableTotals, chainRows, lineGroups, routeTo } from "./tree";

const ln = (run: string, group: string, source: string, target: string, over: Partial<CeilingLine> = {}): CeilingLine => ({
  key: run, group, color: null, from: source.toUpperCase(), to: target.toUpperCase(),
  source, target, transit: false, mark: "3x1.5", length: 1000, ...over,
});

const shape = (rows: ReturnType<typeof chainRows>) =>
  rows.map((r) => (r.kind === "node" ? `[${r.id}]` : `${r.branch ? (r.tail ? "└" : "├") : ""}${r.next ? "→" : ""}${r.line.key}`));

describe("chainRows", () => {
  it("the feed alone, then each box with its lines, the one going on last", () => {
    const rows = chainRows([
      ln("a", "QF1", "board", "k1"), ln("b", "QF1", "k1", "k2"), ln("c", "QF1", "k1", "p1"),
      ln("d", "QF1", "k2", "p2"), ln("e", "QF1", "k2", "p3"),
    ]);
    expect(shape(rows)).toEqual(["a", "[k1]", "├c", "└→b", "[k2]", "├d", "└e"]);
    const k1 = rows[1];
    expect(k1.kind === "node" && k1.keys).toEqual(["b", "c"]);
  });

  it("several lines from the panel: the panel is a node", () => {
    expect(shape(chainRows([ln("a", "TV", "board", "p1"), ln("b", "TV", "board", "p2")]))).toEqual(["[board]", "├a", "└b"]);
  });

  it("a box fed from outside the room starts the chain; a daisy chain goes point to point", () => {
    expect(shape(chainRows([ln("a", "QF1", "k4", "p1"), ln("b", "QF1", "k4", "p2")]))).toEqual(["[k4]", "├a", "└b"]);
    expect(shape(chainRows([ln("a", "QF2", "board", "s1"), ln("b", "QF2", "s1", "s2")]))).toEqual(["a", "[s1]", "└b"]);
  });

  it("a loop does not hang and lists every line", () => {
    expect(chainRows([ln("a", "Q", "x", "y"), ln("b", "Q", "y", "x")])).toHaveLength(4);
  });
});

describe("lineGroups", () => {
  it("panel order, transit groups last, totals per group", () => {
    const groups = lineGroups([
      ln("a", "QF4", "board", "k8", { transit: true }), ln("b", "QF1", "board", "k1", { color: "#f00" }),
      ln("c", "QF1", "k1", "p1", { mark: "3x2.5", length: 500 }),
    ]);
    expect(groups.map((g) => g.group)).toEqual(["QF1", "QF4"]);
    expect(groups[0]).toMatchObject({ color: "#f00", marks: ["3x1.5", "3x2.5"], keys: ["b", "c"], length: 1500, transit: false });
    expect(groups[1].transit).toBe(true);
  });
});

it("cableTotals sums the room part by mark", () => {
  expect(cableTotals([ln("a", "Q", "b", "c"), ln("b", "Q", "b", "d", { mark: "UTP" }), ln("c", "Q", "b", "e")]))
    .toEqual([["3x1.5", 2000], ["UTP", 1000]]);
});

it("routeTo follows the group chain back to its start", () => {
  const lines = [ln("a", "Q", "board", "k1"), ln("b", "Q", "k1", "k2"), ln("c", "Q", "k2", "p")];
  expect(routeTo(lines, lines[2])).toEqual(["BOARD", "K1", "K2", "P"]);
  expect(routeTo(lines, lines[0])).toEqual(["BOARD", "K1"]);
});
