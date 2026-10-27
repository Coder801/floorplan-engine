import { describe, expect, it } from "vitest";
import type { PanelData, PanelDevice } from "../types";
import { bestLayout, busSegments, layout, MODULE, PAD, splitRows, termX } from "./layout";

const dev = (id: string, modules: number, extra: Partial<PanelDevice> = {}): PanelDevice => ({
  id, key: `device:${id}`, kind: "breaker", label: "C16", title: id,
  model: { id: "generic.breaker", brand: "generic", series: "", modules, width: modules * MODULE,
           height: 85, style: "breaker", body: "#fff", lever: "#000" },
  ...extra,
});

const data = (devices: PanelDevice[], external = false): PanelData => ({
  name: "ЩР", phases: 1, scheme: "standard", input: { label: "C40", assumed: true }, devices, groups: {},
  totals: { installed: 0, demand: 1, calculated: 0, current: 0, modules: 0 }, warnings: [],
  texts: { title: "", grid: "", reserve: "" },
  ...(external ? { external: { id: "XP1", kind: "plug", title: "", to: "SA1", feed: null } } : {}),
});

describe("раскладка щита", () => {
  it("аппарат не делится между рейками, порядок сохраняется", () => {
    const devs = [dev("a", 2), dev("b", 3), dev("c", 2), dev("d", 2), dev("e", 2), dev("f", 2)];
    const rows = splitRows(devs, 12);
    expect(rows.map(([, r]) => r.map((d) => d.id))).toEqual([["a", "b", "c", "d", "e"], ["f"]]);
    expect(rows.flatMap(([, r]) => r)).toEqual(devs);
  });

  it("рейки по видам: общие, автоматы, дифавтоматы; резерв — в той же рейке", () => {
    const rows = splitRows([
      dev("QS1", 2, { kind: "input" }), dev("a", 1), dev("d", 2, { kind: "diff" }), dev("KM1", 4, { kind: "ats" }),
      dev("KV1", 3, { kind: "relay" }), dev("r", 1, { reserve: true }), dev("e", 2, { kind: "diff", reserve: true }),
    ], 12);
    expect(rows.map(([k, r]) => [k, r.map((d) => d.id)])).toEqual([
      ["common", ["QS1", "KV1", "KM1"]], ["single", ["a", "r"]], ["double", ["d", "e"]],
    ]);
  });

  it("ширина аппарата — из модели, ряды друг под другом", () => {
    const l = layout(data([dev("a", 2), dev("b", 1), dev("c", 12)]), 12);
    const [a, b, c] = l.placed;
    expect(b.x).toBeCloseTo(a.x + 2 * MODULE);
    expect(c.row).toBe(1);
    expect(c.y).toBeGreaterThan(a.y + a.h);
    expect(l.box.w).toBeCloseTo(12 * MODULE + 2 * PAD);
  });

  it("внешний аппарат резерва — справа от корпуса", () => {
    const l = layout(data([dev("a", 2)], true), 12);
    expect(l.external!.x).toBeGreaterThan(l.box.x + l.box.w);
    expect(l.width).toBeGreaterThan(l.box.w);
  });

  it("узкое высокое окно — рейка уже, широкое низкое — шире", () => {
    const d = data(Array.from({ length: 40 }, (_, k) => dev(`q${k}`, 1)));
    expect(bestLayout(d, 400, 2000).perRow).toBe(12);
    expect(bestLayout(d, 2000, 400).perRow).toBe(24);
  });

  it("шина — отдельно основная и резервная", () => {
    const l = layout(data([dev("a", 1), dev("b", 1), dev("r", 1, { reserve: true })]), 12);
    const segs = [0, 1].flatMap((r) => busSegments(l.placed.filter((p) => p.row === r)));
    expect(segs).toHaveLength(2);
    expect(segs[1][2]).toBe(true);
  });

  it("общие аппараты — не на гребёнке групп; дорожки групп — под рейкой, у левого ниже", () => {
    const l = layout(data([dev("QS1", 2, { kind: "input" }), dev("a", 1, { group: "a" }), dev("b", 1, { group: "b" })]), 12);
    expect(busSegments(l.placed.filter((p) => p.row === 0))).toHaveLength(0);
    const [a, b] = l.placed.filter((p) => p.row === 1);
    expect(busSegments([a, b])[0][0]).toBeCloseTo(a.x);
    expect(b.lane!).toBeGreaterThan(b.y + b.h);
    expect(a.lane!).toBeGreaterThan(b.lane!);
  });

  it("шина PE — над первой рейкой, N — под последней, обе в корпусе", () => {
    const l = layout(data(Array.from({ length: 20 }, (_, k) => dev(`q${k}`, 1))), 12);
    const last = l.rows[l.rows.length - 1];
    expect(l.pe.y + l.pe.h).toBeLessThan(l.rows[0].top);
    expect(l.pe.y).toBeGreaterThan(l.box.y);
    expect(l.n.y).toBeGreaterThan(last.gutterBottom);
    expect(l.n.y + l.n.h).toBeLessThan(l.box.y + l.box.h);
  });

  it("клеммник — по клемме на группу, ввод и запас; клеммы внутри корпуса клеммника", () => {
    const d = data([dev("a", 1, { group: "a" }), dev("b", 1, { group: "b" })]);
    d.groups = { a: {} as never, b: {} as never };
    const l = layout(d, 12);
    expect(l.terminals).toBe(4);
    expect(termX(l.pe, 0)).toBeGreaterThan(l.pe.x);
    expect(termX(l.pe, l.terminals)).toBeLessThan(l.pe.x + l.pe.w);
    expect(l.pe.x + l.pe.w).toBeLessThan(l.box.x + l.box.w);
  });
});
