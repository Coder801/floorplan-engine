import { describe, expect, it } from "vitest";
import type { PanelDc, PanelData, PanelDevice, PanelEnclosure, PanelLed } from "@/shared/types";
import { busSegments, fan, FEED_LANE, FEED_LANE_3, groupPath, LABEL_STEP, layout, MODULE, splitRows, termX } from "./layout";

const dev = (id: string, modules: number, extra: Partial<PanelDevice> = {}): PanelDevice => ({
  id, key: `device:${id}`, kind: "breaker", label: "C16", title: id,
  model: { id: "generic.breaker", brand: "generic", series: "", modules, width: modules * MODULE,
           height: 85, style: "breaker", body: "#fff", lever: "#000" },
  ...extra,
});

// Hager Golf VS212PD / VS318PD, as in panel_catalog.ENCLOSURES
const golf = (rows: number, perRow: 12 | 18): PanelEnclosure => ({
  id: `hager.VS${rows}${perRow}PD`, brand: "hager", series: "Golf", article: `VS${rows}${perRow}PD`,
  title: `Hager Golf VS${rows}${perRow}PD`, rows, per_row: perRow, width: perRow === 12 ? 282 : 390,
  height: [252, 377, 500, 647][rows - 1], depth: 99, pitch: 125, body: "#f6f6f3",
});

const data = (devices: PanelDevice[], enclosure: PanelEnclosure | null = golf(2, 12), external = false): PanelData => ({
  name: "ЩР", phases: 1, scheme: "standard", input: { label: "C40", assumed: true }, enclosure, devices,
  groups: Object.fromEntries(devices.filter((d) => d.group).map((d) => [d.group!, {} as never])),
  totals: { installed: 0, demand: 1, calculated: 0, current: 0, modules: 0 }, warnings: [],
  texts: { title: "", grid: "", reserve: "" },
  ...(external ? { external: { id: "XP1", kind: "plug", title: "", to: "SA1", feed: null } } : {}),
});

// A panel as it comes from the backend: each device has a rail
const rowed = (rows: PanelDevice[][]) => rows.flatMap((r, k) => r.map((d) => ({ ...d, row: k })));

const groups = (n: number, kind = "breaker", modules = 1) =>
  Array.from({ length: n }, (_, k) => dev(`QF${k}`, modules, { kind, group: `QF${k}` }));

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

  it("корпус — габарит щита из каталога, рейка — по центру, рейки — по шагу корпуса", () => {
    const l = layout(data(rowed([[dev("QS1", 2, { kind: "input" })], groups(12)]), golf(3, 12)));
    expect(l.box.w).toBe(282);
    expect(l.box.h).toBe(500);
    expect(l.railX).toBeCloseTo((282 - 12 * MODULE) / 2);
    expect(l.rails).toHaveLength(3);  // including an empty one
    expect(l.rails[1] - l.rails[0]).toBe(125);
    expect((l.rails[0] + l.rails[2]) / 2).toBeCloseTo(l.box.y + l.box.h / 2);
  });

  it("рейка аппарата — с бэка; ширина — из модели", () => {
    const l = layout(data(rowed([[dev("a", 2), dev("b", 1)], [dev("c", 12)]])));
    const [a, b, c] = l.placed;
    expect(b.x).toBeCloseTo(a.x + 2 * MODULE);
    expect(c.row).toBe(1);
    expect(c.y).toBeGreaterThan(a.y + a.h);
  });

  it("аппараты не выходят за корпус, пучок не налезает на следующую рейку", () => {
    for (const [enc, rows] of [
      [golf(2, 12), [[dev("QS1", 2, { kind: "input" }), dev("KV1", 3, { kind: "relay", model: { ...dev("x", 3).model, height: 90 } })], groups(12)]],
      [golf(3, 18), [[dev("QS1", 2, { kind: "input" })], groups(18), groups(9, "diff", 2)]],
      [golf(4, 12), [[dev("QS1", 2, { kind: "input" })], groups(12), groups(12), groups(6, "diff", 2)]],
    ] as const) {
      const l = layout(data(rowed(rows.map((r) => [...r])), enc));
      for (const p of l.placed) {
        expect(p.x).toBeGreaterThanOrEqual(l.box.x);
        expect(p.x + p.w).toBeLessThanOrEqual(l.box.x + l.box.w);
        expect(p.y).toBeGreaterThanOrEqual(l.box.y);
        expect(p.y + p.h).toBeLessThanOrEqual(l.box.y + l.box.h);
      }
      l.rows.forEach((row, r) => {
        const next = l.rows[r + 1];
        expect(row.gutterBottom).toBeLessThanOrEqual(next ? next.top : l.n.y);
        expect(row.pitch).toBeGreaterThan(0);
      });
    }
  });

  it("внешний аппарат резерва — справа от корпуса, подписи — под ним", () => {
    const l = layout(data(rowed([[dev("SA1", 3, { kind: "changeover" })], groups(4)]), golf(2, 12), true));
    expect(l.external!.x).toBeGreaterThan(l.box.x + l.box.w);
    expect(l.width).toBeGreaterThan(l.box.w);
    for (const p of l.placed.filter((q) => q.label !== null)) {
      expect(p.label!).toBeGreaterThan(l.external!.y + l.external!.h);
    }
  });

  it("шина — отдельно основная и резервная", () => {
    const l = layout(data(rowed([[dev("a", 1), dev("b", 1), dev("r", 1, { reserve: true })]])));
    const segs = busSegments(l.placed.filter((p) => p.row === 0));
    expect(segs).toHaveLength(2);
    expect(segs[1][2]).toBe(true);
  });

  it("мастер-выключатель делит шину: за контактором — своя секция, контактор — общий аппарат", () => {
    const km = dev("KM2", 2, { kind: "contactor", master: true });
    const l = layout(data(rowed([[km], [dev("a", 1), dev("m", 1, { master: true }), dev("r", 1, { reserve: true, master: true })]])));
    expect(l.rows[0].kind).toBe("common");
    const segs = busSegments(l.placed.filter((p) => p.row === 1));
    expect(segs.map((s) => [s[2], s[3]])).toEqual([[false, false], [false, true], [true, true]]);
    expect(l.rows[0].gutterBottom - l.rows[0].gutterTop).toBeGreaterThanOrEqual(FEED_LANE + 6);
  });

  it("провода групп — тонким пучком под рейкой, у левого ниже; подписи — по порядку проводов", () => {
    const l = layout(data(rowed([[dev("QS1", 2, { kind: "input" })], groups(12)])));
    expect(busSegments(l.placed.filter((p) => p.row === 0))).toHaveLength(0);
    const row = l.placed.filter((p) => p.row === 1);
    expect(row[0].lane!).toBeGreaterThan(row[11].lane!);
    expect(row[11].lane!).toBeGreaterThan(row[11].y + row[11].h);
    expect(l.rows[1].pitch).toBeLessThanOrEqual(3);
    // Wires top to bottom map to labels top to bottom, at least a step apart: a fan with no crossings
    const byLane = [...row].sort((a, b) => a.lane! - b.lane!);
    byLane.slice(1).forEach((p, k) => expect(p.label! - byLane[k].label!).toBeGreaterThanOrEqual(LABEL_STEP - 1e-9));
    // Inside the enclosure the wire is horizontal; outside it goes to the label
    const path = groupPath(l, row[0]);
    expect(path[2][1]).toBe(row[0].lane);
    expect(path[2][0]).toBeGreaterThan(l.box.x + l.box.w);
    expect(path[3]).toEqual([l.labelX - 3, row[0].label]);
  });

  it("веер подписей: свободные — у своего провода, слипшиеся — группой по центру", () => {
    expect(fan([0, 100], 10, -Infinity)).toEqual([0, 100]);
    expect(fan([50, 51, 52], 10, -Infinity)).toEqual([41, 51, 61]);
    expect(fan([50, 51, 52], 10, 45)).toEqual([45, 55, 65]);
  });

  it("без корпуса в данных (старый .epd) — корпус по месту", () => {
    const l = layout(data(groups(30), null));
    expect(l.enclosure.per_row).toBe(18);
    expect(l.rows).toHaveLength(2);
    for (const p of l.placed) expect(p.x + p.w).toBeLessThanOrEqual(l.box.x + l.box.w);
  });

  it("шина PE — над первой рейкой, N — под последней, обе в корпусе", () => {
    const l = layout(data(rowed([groups(12), groups(8)])));
    const last = l.rows[l.rows.length - 1];
    expect(l.pe.y + l.pe.h).toBeLessThan(l.rows[0].top);
    expect(l.pe.y).toBeGreaterThan(l.box.y);
    expect(l.n.y).toBeGreaterThan(last.gutterBottom);
    expect(l.n.y + l.n.h).toBeLessThan(l.box.y + l.box.h);
  });

  it("клеммник — по клемме на группу, ввод и запас; клеммы внутри корпуса клеммника", () => {
    const l = layout(data(rowed([groups(2)])));
    expect(l.terminals).toBe(4);
    expect(termX(l.pe, 0)).toBeGreaterThan(l.pe.x);
    expect(termX(l.pe, l.terminals)).toBeLessThan(l.pe.x + l.pe.w);
    expect(l.pe.x + l.pe.w).toBeLessThan(l.box.x + l.box.w);
  });

  it("щит АКБ — справа от подписей, под инвертором; дорожки без пересечений, АКБ под корпусом", () => {
    const dcDevs = rowed([[dev("QB1", 3, { kind: "dc_battery" }), dev("QP1", 2, { kind: "dc_breaker" }),
                           dev("FP1", 3, { kind: "dc_spd" })]]);
    const dc: PanelDc = {
      enclosure: golf(1, 12), devices: dcDevs, pv_strings: 1,
      battery: { voltage: 48, voltage_assumed: true, capacity: null, power: 5, power_assumed: true,
                 current: 104.2, rating: 125, cable: 35 },
      texts: { title: "", battery: "", pv: "" },
    };
    const d = data(rowed([[dev("QS1", 2, { kind: "input" }), dev("SA1", 3, { kind: "changeover" })], groups(6)]),
                   golf(2, 12), true);
    d.external = { id: "U1", kind: "inverter", title: "", to: "SA1", feed: null };
    d.dc = dc;
    const l = layout(d);
    const x = l.dc!;
    expect(x.box.x).toBeGreaterThan(l.labelX + 290);
    expect(x.box.x).toBeGreaterThan(l.external!.x + l.external!.w);
    expect(x.lanes).toHaveLength(4);  // battery + −, string + −
    // The right-hand wire gets the higher lane; all lanes are between the inverter and the enclosure
    x.lanes.slice(1).forEach((y, k) => expect(y).toBeLessThan(x.lanes[k]));
    expect(Math.min(...x.lanes)).toBeGreaterThan(l.external!.y + l.external!.h);
    expect(Math.max(...x.lanes)).toBeLessThan(x.box.y);
    for (const p of x.placed) expect(p.x + p.w).toBeLessThanOrEqual(x.box.x + x.box.w);
    expect(x.battery.y).toBeGreaterThan(Math.max(...x.pvLanes));
    expect(l.height).toBeGreaterThan(x.battery.y + x.battery.h);
    // Group labels sit below the battery box lanes
    for (const p of l.placed.filter((q) => q.label !== null)) expect(p.label!).toBeGreaterThan(Math.max(...x.lanes));
  });
});

describe("щит блоков питания LED", () => {
  const psu = (id: string, modules: number) => dev(id, modules, { kind: "led_psu_din", label: "60 Вт 12 В", row: 0 });
  const led = (devices: PanelDevice[]): PanelLed => ({
    enclosure: golf(1, 12), devices, voltage: 12, drop_max: 5,
    lines: devices.map((d, k) => ({ device: d.id, point: `led${k}`, group: "QF1", color: null, metres: 5,
                                    metres_assumed: true, power: 72, power_assumed: true, supply: 100, current: 6 })),
    texts: { title: "", strip: "лента {m} м", from: "" },
  });

  it("под основным щитом, блоки в ряд по ширине; линии 12 В — пучком без пересечений, подписи ниже групп", () => {
    const base = data(rowed([[dev("QS1", 2, { kind: "input" })], groups(6)]), golf(2, 12));
    const l = layout({ ...base, led: led([psu("G1", 4), psu("G2", 3), psu("G3", 1)]) });
    const box = l.led!.box;
    expect(box.y).toBeGreaterThan(l.box.y + l.box.h);
    expect(box.x).toBe(l.box.x);
    const [a, b, c] = l.led!.placed;
    expect(b.x).toBeCloseTo(a.x + 4 * MODULE);
    expect(c.x).toBeCloseTo(b.x + 3 * MODULE);
    for (const p of l.led!.placed) {
      expect(p.x + p.w).toBeLessThanOrEqual(box.x + box.w);
      expect(p.lane!).toBeGreaterThan(p.y + p.h);
      expect(p.lane!).toBeLessThan(box.y + box.h);
    }
    expect(a.lane!).toBeGreaterThan(b.lane!);  // the left one lower: no crossings
    expect(b.lane!).toBeGreaterThan(c.lane!);
    const groupLabels = l.placed.filter((p) => p.label !== null).map((p) => p.label!);
    const ledLabels = l.led!.placed.map((p) => p.label!);
    expect(Math.min(...ledLabels)).toBeGreaterThan(Math.max(...groupLabels));
    expect(l.height).toBeGreaterThanOrEqual(box.y + box.h);
  });

  it("без блоков в щите — второго щита нет", () => {
    expect(layout(data(rowed([groups(3)]))).led).toBeNull();
  });
});

describe("три фазы", () => {
  it("под общими аппаратами — место под перемычку и ствол каждой фазы", () => {
    const devs = rowed([[dev("QS1", 4, { kind: "input" }), dev("KV1", 3, { kind: "relay", phase: "L1" })], groups(3)]);
    const one = layout(data(devs)), three = layout({ ...data(devs), phases: 3 });
    const lane = (l: ReturnType<typeof layout>) => l.rows[0].gutterBottom - l.rows[0].gutterTop;
    expect(lane(three) - lane(one)).toBe(FEED_LANE_3 - FEED_LANE);
  });
});
