// Panel front view layout, panel mm (Y axis down). The enclosure is a real catalogue panel
// (enclosure: Hager Golf…) at full size: rails at its pitch, centred in the enclosure, empty
// rails visible too. The backend places devices on rails (panel.panel_rows: shared, breakers,
// RCBOs, each kind from its own rail) so none sticks out of a rail; a device is centred on the
// rail axis (DIN 43880), its width comes from the catalogue model. Power comes from the top
// (busbar above the devices), groups go from the bottom terminals down into a bundle under the
// rail: thin wires packed tight, lower for the leftmost device, no crossings; the bundle exits
// through the right wall, and outside the enclosure a wire goes at any angle to its label
// (labels in a column, in wire order). PE terminal block at the top of the enclosure, N at the
// bottom. A hybrid inverter gets a battery box (dc): right of the label column, under the
// inverter; its wires go up into the inverter's BAT and PV inputs along their own lanes (the
// right-hand wire higher, no crossings), the battery under it, solar strings exit down and
// right to their label. LED supplies in the panel get a box of their own under it (led): the
// feed from its group breaker comes from the top, the 12 V line from the bottom terminals into a
// bundle under the rail and out through the right wall to its label in the same column, below
// the group labels. Pure functions, no canvas, with tests.

import type { PanelDc, PanelData, PanelDevice, PanelEnclosure, PanelLed } from "@/shared/types";
import { SCREW } from "./catalog";

export const MODULE = 17.5;     // DIN module width, mm
export const LANE_MAX = 3;      // wire step in the group bundle, mm: at most
export const LANE_MIN = 0.9;    // and at least, otherwise the bundle spills onto the next rail
export const LANE_PAD = 2;      // from the device bottom to the bundle and from the bundle to the next rail
export const RESERVE_TAG = 5;   // above the backup bus: its label
export const FEED_LANE = 17;    // under the shared devices: the inverter feed is below the jumpers
export const FEED_LANE_3 = 26;  // three phases: a jumper and a trunk per phase above it
export const MASTER_LANES = 6;  // master switch contactors: two more lanes above the inverter feed
// Above the devices: busbars (phase, neutral for RCBOs) and the backup entry
export const HEAD = { common: 16, single: 13, double: 17 } as const;
export const FAN = 46;          // from the enclosure to the labels: wires fan out at an angle
export const STUB = 5;          // straight wire exit from the enclosure before the bend
export const LABEL_STEP = 10;   // group label step
export const LABELS = 300;      // group label column
export const LEAD = 60;         // supply above the panel
export const SIDE = 50;         // from the enclosure to the inverter or plug: a gap for its wires
// Inverter: proportions of a 5 kW hybrid (330 × 580 mm); its height runs from the top of the
// drawing to the shared rail bundles: its wires come from below and do not cross the labels
export const INVERTER = { top: 10, ratio: 330 / 580, gap: 16 } as const;
export const BUS_X = 8;         // from the enclosure wall to the terminal block
// N / PE terminal block in the enclosure (like Hager QuickConnect): a foot, a screw input
// terminal, a row of screwless terminals, a tag, a foot
export const TERM = { h: 22, foot: 5, big: 12, pitch: 7, tag: 14 } as const;
export const TERM_PAD = 26;     // from the enclosure top and bottom to the terminal block middle
// Battery box: from the inverter bottom to the lanes (the inverter LOAD and PE wires are below),
// the lane step, from the lanes to the enclosure; under the enclosure, solar string and battery wires
export const DC = { gap: 24, lane: 4.5, top: 14, pv: 14, battery: { w: 150, h: 190, gap: 22 } } as const;

// Shared devices in rail order; main power goes main switch → relay, backup power comes from
// the ATS (or switch)
const COMMON = ["input", "relay", "spd", "changeover", "ats", "output", "feed", "contactor"];
export const CHAIN = new Set(["input", "relay"]);
export const BACKUP = new Set(["ats", "changeover"]);

export type RowKind = "common" | "single" | "double";

export function rowKind(d: PanelDevice): RowKind {
  return COMMON.includes(d.kind) ? "common" : d.kind === "diff" ? "double" : "single";
}

export interface Rect { x: number; y: number; w: number; h: number }

export interface Placed extends Rect {
  dev: PanelDevice;
  row: number;
  lane: number | null;   // y of the group wire in the bundle or of the inverter feed; null if none
  label: number | null;  // y of the group label outside the enclosure
}

export interface Row {
  kind: RowKind;
  top: number;          // top of the row (busbars above the devices)
  devTop: number;       // top of the devices
  devH: number;         // height of the tallest device; the rail axis is devTop + devH / 2
  gutterTop: number;    // bottom of the devices
  gutterBottom: number; // bottom of the wire bundle
  pitch: number;        // wire step in the bundle
}

export interface DcLayout {
  box: Rect;
  enclosure: PanelEnclosure;
  rails: number[];
  placed: Placed[];
  lanes: number[];      // y of a wire lane to the inverter: battery +, −, string 1 +, − …
  pvLanes: number[];    // y of solar string wires under the enclosure: string 1 +, − …
  battery: Rect;
}

export interface LedLayout {
  box: Rect;
  enclosure: PanelEnclosure;
  rails: number[];
  placed: Placed[];     // lane — y of the 12 V line in the bundle, label — y of its label
  title: number;        // y of the box title
  feed: number;         // y of the feed tags above the supplies
}

export interface PanelLayout {
  enclosure: PanelEnclosure;
  perRow: number;
  width: number;        // everything together: supply, panel, labels, external device
  height: number;
  box: Rect;            // panel enclosure
  railX: number;        // rail start (first module)
  rails: number[];      // axes of all enclosure rails, empty ones too
  rows: Row[];
  placed: Placed[];
  external: Rect | null;
  labelX: number;       // start of the group labels
  pe: Rect;             // PE terminal block
  n: Rect;              // N terminal block
  terminals: number;    // small terminals in the block
  dc: DcLayout | null;  // battery box at the inverter
  led: LedLayout | null;  // LED supplies box under the panel
}

// Rails by kind: shared, breakers, RCBOs; within a kind in data order (main first, then
// backup), shared ones in COMMON order; a device is never split between rails. The backend
// lays them out the same way (panel.panel_rows); this is for an .epd without rails on devices
export function splitRows(devices: PanelDevice[], perRow: number): [RowKind, PanelDevice[]][] {
  const rows: [RowKind, PanelDevice[]][] = [];
  for (const kind of ["common", "single", "double"] as const) {
    let devs = devices.filter((d) => rowKind(d) === kind);
    if (kind === "common") devs = [...devs].sort((a, b) => COMMON.indexOf(a.kind) - COMMON.indexOf(b.kind));
    let used = perRow + 1;
    for (const d of devs) {
      const m = d.model.modules;
      if (used + m > perRow) { rows.push([kind, []]); used = 0; }
      rows[rows.length - 1][1].push(d);
      used += m;
    }
  }
  return rows;
}

// On-site enclosure (like panel_catalog.fitted_enclosure), for an .epd without an enclosure
export function fittedEnclosure(rows: number, perRow: number): PanelEnclosure {
  return { id: `fitted.${rows}x${perRow}`, brand: "", series: "", article: "", title: `${rows}×${perRow}`,
           rows, per_row: perRow, width: perRow * MODULE + 75, height: 252 + (rows - 1) * 125,
           depth: 99, pitch: 125, body: "#f6f6f3" };
}

// Devices by rail: from the data (row on the device), otherwise splitRows
function devRows(data: PanelData, perRow: number): [RowKind, PanelDevice[]][] {
  if (!data.devices.every((d) => d.row !== undefined)) return splitRows(data.devices, perRow);
  const out: [RowKind, PanelDevice[]][] = [];
  for (const d of data.devices) {
    while (out.length <= d.row!) out.push(["single", []]);
    out[d.row!][1].push(d);
  }
  for (const r of out) {
    if (r[1].length) r[0] = rowKind(r[1][0]);
    if (r[0] === "common") r[1].sort((a, b) => COMMON.indexOf(a.kind) - COMMON.indexOf(b.kind));
  }
  return out;
}

// Labels in a column: as close to wanted as possible (ascending), at least step apart and not
// above lo; clumped ones form a group centred on their wires
export function fan(wanted: readonly number[], step: number, lo: number): number[] {
  const groups: { start: number; n: number; sum: number }[] = [];
  for (const w of wanted) {
    groups.push({ start: Math.max(w, lo), n: 1, sum: w });
    while (groups.length > 1) {
      const b = groups[groups.length - 1], a = groups[groups.length - 2];
      if (a.start + a.n * step <= b.start + 1e-9) break;
      groups.pop();
      a.n += b.n; a.sum += b.sum;
      a.start = Math.max(lo, a.sum / a.n - ((a.n - 1) * step) / 2);
    }
  }
  return groups.flatMap((g) => Array.from({ length: g.n }, (_, k) => g.start + k * step));
}

export function layout(data: PanelData): PanelLayout {
  const enc = data.enclosure ?? fittedEnclosure(splitRows(data.devices, 18).length, 18);
  const perRow = enc.per_row;
  const split = devRows(data, perRow);
  const box = { x: 0, y: LEAD, w: enc.width, h: enc.height };
  const railX = (box.w - perRow * MODULE) / 2;
  const first = box.y + (box.h - (enc.rows - 1) * enc.pitch) / 2;
  const rails = Array.from({ length: Math.max(enc.rows, split.length) }, (_, k) => first + k * enc.pitch);
  // Terminal blocks centred in the enclosure: terminals per group, input and spare, but no longer than the enclosure
  const room = box.w - 2 * BUS_X;
  const terminals = Math.max(2, Math.min(Object.keys(data.groups).length + 2,
                                         Math.floor((room - termWidth(0)) / TERM.pitch)));
  const tw = termWidth(terminals);
  const bar = (by: number) => ({ x: (box.w - tw) / 2, y: by - TERM.h / 2, w: tw, h: TERM.h });
  const pe = bar(box.y + TERM_PAD), n = bar(box.y + box.h - TERM_PAD);

  const rows: Row[] = [];
  const placed: Placed[] = [];
  // A wire of its own for groups and for the external device feed (inverter)
  const out = (d: PanelDevice) => !!d.group || d.id === data.external?.feed;
  const devH = split.map(([, devs]) => Math.max(...devs.map((d) => d.model.height), 0));
  split.forEach(([kind, devs], r) => {
    const devTop = rails[r] - devH[r] / 2;
    const gutterTop = devTop + devH[r];
    // The bundle goes down to the next rail's busbars (or to the top of an empty rail, the N terminal block)
    const after = split[r + 1];
    const next = after ? rails[r + 1] - devH[r + 1] / 2 - HEAD[after[0]] - (after[1].some((d) => d.reserve || d.master) ? RESERVE_TAG : 0)
      : Math.min(n.y, r + 1 < rails.length ? rails[r + 1] - 45 : Infinity);
    const lanesTop = gutterTop + (kind === "common" ? feedLane(data) : LANE_PAD);
    const lanes = devs.filter(out).length;
    const pitch = Math.max(LANE_MIN, Math.min(LANE_MAX, (next - LANE_PAD - lanesTop) / Math.max(1, lanes)));
    rows.push({ kind, top: devTop - HEAD[kind], devTop, devH: devH[r], gutterTop,
                gutterBottom: lanesTop + lanes * pitch, pitch });
    let x = railX, k = lanes;
    for (const d of devs) {
      const lane = out(d) ? lanesTop + (--k + 0.5) * pitch : null;
      placed.push({ dev: d, row: r, lane, label: null, x, y: rails[r] - d.model.height / 2,
                    w: d.model.width, h: d.model.height });
      x += d.model.width;
    }
  });
  const common = rows.find((r) => r.kind === "common");
  const commonLanes = common ? common.gutterTop + feedLane(data) : box.y + 120;
  const eh = Math.max(120, commonLanes - INVERTER.gap - INVERTER.top);
  // Above the label column: the inverter bottom is above all group wires
  const external = data.external
    ? { x: box.w + SIDE * 1.2, y: INVERTER.top, w: eh * INVERTER.ratio, h: eh }
    : null;
  const labelX = box.w + FAN;
  const dc = external && data.dc
    ? dcLayout(data.dc, external, Math.max(labelX + LABELS, external.x + external.w) + SIDE) : null;
  // Group labels follow wire order top to bottom: a fan with no crossings; below the inverter
  // and the battery box lanes
  const groups = placed.filter((p) => p.lane !== null && p.dev.group).sort((a, b) => a.lane! - b.lane!);
  const lo = dc ? Math.max(...dc.lanes) + LABEL_STEP
    : external ? external.y + external.h + LABEL_STEP : box.y + LABEL_STEP / 2;
  fan(groups.map((p) => p.lane!), LABEL_STEP, lo).forEach((y, k) => { groups[k].label = y; });
  const lastLabel = groups.length ? groups[groups.length - 1].label! + LABEL_STEP / 2 : 0;
  // A box wider than the panel reaches the label column: then it goes below the group labels
  const ledTop = box.y + box.h + (data.led && data.led.enclosure.width > labelX ? Math.max(0, lastLabel - box.y - box.h) : 0);
  const led = data.led ? ledLayout(data.led, ledTop, lastLabel + LABEL_STEP) : null;
  const ledLabels = led ? led.placed.map((p) => p.label ?? 0) : [];
  const width = Math.max(labelX + LABELS, external ? external.x + external.w + SIDE / 5 : 0,
                         dc ? dc.box.x + dc.box.w + DC_LABEL : 0, led ? led.box.x + led.box.w : 0);
  const height = Math.max(box.y + box.h, lastLabel, dc ? dc.battery.y + dc.battery.h + 14 : 0,
                          led ? led.box.y + led.box.h + 10 : 0, ...ledLabels.map((y) => y + LABEL_STEP / 2));
  return { enclosure: enc, perRow, width, height, box, railX, rails, rows, placed, external, labelX,
           pe, n, terminals, dc, led };
}

// LED box: the title, the feed tags and the box under the panel; supplies on their rails (row
// from the backend), the 12 V line from the bottom terminal into a bundle under the rail (lower
// for the left supply, no crossings), labels in the group label column, not above lo
export const LED = { gap: 64, title: 40, feed: 14 } as const;

export function ledLayout(led: PanelLed, top: number, lo: number): LedLayout {
  const enc = led.enclosure;
  const box = { x: 0, y: top + LED.gap, w: enc.width, h: enc.height };
  const railX = box.x + (box.w - enc.per_row * MODULE) / 2;
  const first = box.y + (box.h - (enc.rows - 1) * enc.pitch) / 2;
  const rows = Math.max(enc.rows, ...led.devices.map((d) => (d.row ?? 0) + 1));
  const rails = Array.from({ length: rows }, (_, k) => first + k * enc.pitch);
  const placed: Placed[] = [];
  const used: number[] = [];
  for (const d of led.devices) {
    const r = d.row ?? 0;
    used[r] = used[r] ?? railX;
    placed.push({ dev: d, row: r, lane: null, label: null, x: used[r], y: rails[r] - d.model.height / 2,
                  w: d.model.width, h: d.model.height });
    used[r] += d.model.width;
  }
  rails.forEach((_, r) => {
    const mine = placed.filter((p) => p.row === r);
    const bottom = Math.max(0, ...mine.map((p) => p.y + p.h));
    const room = (r + 1 < rails.length ? rails[r + 1] - 45 : box.y + box.h - 8) - bottom - LANE_PAD;
    const pitch = Math.max(LANE_MIN, Math.min(LANE_MAX, room / Math.max(1, mine.length)));
    let k = mine.length;
    for (const p of mine) p.lane = bottom + LANE_PAD + (--k + 0.5) * pitch;
  });
  const lines = [...placed].sort((a, b) => a.lane! - b.lane!);
  fan(lines.map((p) => p.lane!), LABEL_STEP, Math.max(lo, box.y)).forEach((y, k) => { lines[k].label = y; });
  return { box, enclosure: enc, rails, placed, title: box.y - LED.title, feed: box.y - LED.feed };
}

const DC_LABEL = 80;  // right of the battery box: solar string labels

// Under the shared devices, from the device bottom to the inverter feed lane
export const feedLane = (data: PanelData) => (data.phases === 3 ? FEED_LANE_3 : FEED_LANE)
  + (data.devices.some((d) => d.kind === "contactor") ? MASTER_LANES : 0);

// A group device behind a master switch contactor (the contactor itself hangs on its bus)
export const behindMaster = (d: PanelDevice) => !!d.master && d.kind !== "contactor";

// Battery box: lanes to the inverter under it, the enclosure below, devices on rails (row from
// the backend), solar string wires under the enclosure (lower for the left string), the battery
// under the battery breaker
export function dcLayout(dc: PanelDc, inv: Rect, x: number): DcLayout {
  const enc = dc.enclosure;
  const wires = 2 + 2 * dc.pv_strings;
  const lanesTop = inv.y + inv.h + DC.gap;
  const lanes = Array.from({ length: wires }, (_, k) => lanesTop + (wires - 1 - k) * DC.lane);
  const box = { x, y: lanesTop + wires * DC.lane + DC.top, w: enc.width, h: enc.height };
  const railX = box.x + (box.w - enc.per_row * MODULE) / 2;
  const first = box.y + (box.h - (enc.rows - 1) * enc.pitch) / 2;
  const rails = Array.from({ length: enc.rows }, (_, k) => first + k * enc.pitch);
  const placed: Placed[] = [];
  const used: number[] = [];
  for (const d of dc.devices) {
    const r = d.row ?? 0;
    used[r] = used[r] ?? railX;
    placed.push({ dev: d, row: r, lane: null, label: null, x: used[r], y: rails[r] - d.model.height / 2,
                  w: d.model.width, h: d.model.height });
    used[r] += d.model.width;
  }
  const strings = 2 * dc.pv_strings;
  const bottom = box.y + box.h;
  const pvLanes = Array.from({ length: strings }, (_, k) => bottom + DC.pv + (strings - 1 - k) * DC.lane);
  const battery = { x: box.x + 8, y: bottom + DC.pv + strings * DC.lane + DC.battery.gap,
                    w: DC.battery.w, h: DC.battery.h };
  return { box, enclosure: enc, rails, placed, lanes, pvLanes, battery };
}

export function termWidth(n: number): number {
  return 2 * TERM.foot + TERM.big + n * TERM.pitch + TERM.tag;
}

// Terminal centre: 0 is the input terminal, 1… the small ones
export function termX(r: Rect, k: number): number {
  return k === 0 ? r.x + TERM.foot + TERM.big / 2 : r.x + TERM.foot + TERM.big + (k - 0.5) * TERM.pitch;
}

// Group wire: from the bottom terminal down into the bundle, along the bundle to the right
// wall, a short straight run and then at an angle to the label
export function groupPath(l: PanelLayout, p: Placed): [number, number][] {
  const right = l.box.x + l.box.w, from = p.y + p.h - SCREW;
  const cx = p.x + MODULE / 2;
  const pts: [number, number][] = [[cx, from], [cx, p.lane!], [right + STUB, p.lane!]];
  if (p.label !== null) pts.push([l.labelX - 3, p.label]);
  return pts;
}

// Phase busbar sections above a group rail: main and backup separately, each split again by the
// master switch contactor, [x0, x1, backup, master]; from the first device of a section to the
// end of the last
export function busSegments(row: Placed[]): [number, number, boolean, boolean][] {
  const out: [number, number, boolean, boolean][] = [];
  for (const reserve of [false, true]) {
    for (const master of [false, true]) {
      const xs = row.filter((p) => !!p.dev.reserve === reserve && behindMaster(p.dev) === master
        && rowKind(p.dev) !== "common");
      if (xs.length) out.push([xs[0].x, xs[xs.length - 1].x + xs[xs.length - 1].w, reserve, master]);
    }
  }
  return out;
}
