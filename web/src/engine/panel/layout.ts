// Раскладка щита в лицо, мм щита (ось Y вниз). Корпус — реальный щит из каталога
// (enclosure: Hager Golf…) в натуральную величину: рейки по его шагу, по центру корпуса,
// пустые рейки тоже видны. Аппараты по рейкам кладёт бэк (panel.panel_rows: общие, автоматы,
// дифавтоматы — каждый вид со своей рейки) так, что ни один не выходит за рейку; аппарат —
// серединой на оси рейки (DIN 43880), ширина — из модели каталога. Питание сверху (гребёнка
// над аппаратами), группы — из нижних клемм вниз в пучок под рейкой: тонкие провода плотно,
// у левого аппарата ниже, без пересечений; пучок выходит в правую стенку, а за корпусом
// провод идёт под любым углом к своей подписи (подписи — колонкой, по порядку проводов).
// Вверху корпуса — клеммник PE, внизу — N. У гибридного инвертора — щит АКБ (dc): справа
// от колонки подписей, под инвертором; его провода — вверх в вводы BAT и PV инвертора
// своими дорожками (у правого провода выше — без пересечений), под ним — АКБ, строки панелей
// выходят вниз и вправо к подписи. Чистые функции — без canvas, с тестами.

import type { PanelDc, PanelData, PanelDevice, PanelEnclosure } from "@/shared/types";
import { SCREW } from "./catalog";

export const MODULE = 17.5;     // ширина модуля DIN, мм
export const LANE_MAX = 3;      // шаг проводов в пучке групп, мм: не больше
export const LANE_MIN = 0.9;    // и не меньше — иначе пучок вылезет на соседнюю рейку
export const LANE_PAD = 2;      // от низа аппарата до пучка и от пучка до следующей рейки
export const RESERVE_TAG = 5;   // над резервной шиной — её подпись
export const FEED_LANE = 17;    // под общими аппаратами: ниже перемычек — питание инвертора
// Над аппаратами: гребёнки (фазная, нулевая у дифавтоматов) и подход резерва
export const HEAD = { common: 16, single: 13, double: 17 } as const;
export const FAN = 46;          // от корпуса до подписей — провода веером под углом
export const STUB = 5;          // прямой выход провода из корпуса до поворота
export const LABEL_STEP = 10;   // шаг подписей групп
export const LABELS = 300;      // колонка подписей групп
export const LEAD = 60;         // ввод над щитом
export const SIDE = 50;         // от корпуса до инвертора или вилки — просвет для его проводов
// Инвертор — пропорции гибридного на 5 кВт (330 × 580 мм); высота — от верха чертежа до
// пучков общей рейки: его провода приходят снизу и не пересекают подписи
export const INVERTER = { top: 10, ratio: 330 / 580, gap: 16 } as const;
export const BUS_X = 8;         // от стенки щита до клеммника
// Клеммник N / PE в корпусе (как Hager QuickConnect): лапка, вводная клемма под винт, ряд
// безвинтовых клемм, бирка, лапка
export const TERM = { h: 22, foot: 5, big: 12, pitch: 7, tag: 14 } as const;
export const TERM_PAD = 26;     // от верха и низа корпуса до середины клеммника
// Щит АКБ: от низа инвертора до дорожек (ниже — провода LOAD и PE инвертора), шаг дорожек,
// от дорожек до корпуса; под корпусом — провода строк панелей и АКБ
export const DC = { gap: 24, lane: 4.5, top: 14, pv: 14, battery: { w: 150, h: 190, gap: 22 } } as const;

// Общие аппараты — в порядке на рейке; питание основной сети идёт ввод → реле, резервной —
// от АВР (или переключателя)
const COMMON = ["input", "relay", "spd", "changeover", "ats", "output", "feed"];
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
  lane: number | null;   // y провода группы в пучке или питания инвертора; нет — null
  label: number | null;  // y подписи группы за корпусом
}

export interface Row {
  kind: RowKind;
  top: number;          // верх ряда (гребёнки над аппаратами)
  devTop: number;       // верх аппаратов
  devH: number;         // высота самого высокого аппарата; ось рейки — devTop + devH / 2
  gutterTop: number;    // низ аппаратов
  gutterBottom: number; // низ пучка проводов
  pitch: number;        // шаг проводов в пучке
}

export interface DcLayout {
  box: Rect;
  enclosure: PanelEnclosure;
  rails: number[];
  placed: Placed[];
  lanes: number[];      // y дорожки провода к инвертору: АКБ +, −, строка 1 +, − …
  pvLanes: number[];    // y проводов строк панелей под корпусом: строка 1 +, − …
  battery: Rect;
}

export interface PanelLayout {
  enclosure: PanelEnclosure;
  perRow: number;
  width: number;        // всё вместе: ввод, щит, подписи, внешний аппарат
  height: number;
  box: Rect;            // корпус щита
  railX: number;        // начало рейки (первый модуль)
  rails: number[];      // оси всех реек корпуса, и пустых
  rows: Row[];
  placed: Placed[];
  external: Rect | null;
  labelX: number;       // начало подписей групп
  pe: Rect;             // клеммник PE
  n: Rect;              // клеммник N
  terminals: number;    // малых клемм в клеммнике
  dc: DcLayout | null;  // щит АКБ у инвертора
}

// Рейки по видам: общие, автоматы, дифавтоматы; внутри вида — порядок данных (основные,
// потом резервные), общие — в порядке COMMON; аппарат не делится между рейками. Так же
// раскладывает бэк (panel.panel_rows); здесь — для .epd без рейки у аппарата
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

// Корпус по месту (как panel_catalog.fitted_enclosure) — у .epd без корпуса
export function fittedEnclosure(rows: number, perRow: number): PanelEnclosure {
  return { id: `fitted.${rows}x${perRow}`, brand: "", series: "", article: "", title: `${rows}×${perRow}`,
           rows, per_row: perRow, width: perRow * MODULE + 75, height: 252 + (rows - 1) * 125,
           depth: 99, pitch: 125, body: "#f6f6f3" };
}

// Аппараты по рейкам: из данных (row у аппарата), иначе — splitRows
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

// Подписи колонкой: как можно ближе к wanted (по возрастанию), не ближе step друг к другу
// и не выше lo; слипшиеся — группой по центру своих проводов
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
  // Клеммники — по центру корпуса: клемм по группе, вводу и запасу, но не длиннее корпуса
  const room = box.w - 2 * BUS_X;
  const terminals = Math.max(2, Math.min(Object.keys(data.groups).length + 2,
                                         Math.floor((room - termWidth(0)) / TERM.pitch)));
  const tw = termWidth(terminals);
  const bar = (by: number) => ({ x: (box.w - tw) / 2, y: by - TERM.h / 2, w: tw, h: TERM.h });
  const pe = bar(box.y + TERM_PAD), n = bar(box.y + box.h - TERM_PAD);

  const rows: Row[] = [];
  const placed: Placed[] = [];
  // Свой провод — у групп и у питания внешнего аппарата (инвертора)
  const out = (d: PanelDevice) => !!d.group || d.id === data.external?.feed;
  const devH = split.map(([, devs]) => Math.max(...devs.map((d) => d.model.height), 0));
  split.forEach(([kind, devs], r) => {
    const devTop = rails[r] - devH[r] / 2;
    const gutterTop = devTop + devH[r];
    // Пучок — до гребёнок следующей рейки (или до верха пустой рейки, клеммника N)
    const after = split[r + 1];
    const next = after ? rails[r + 1] - devH[r + 1] / 2 - HEAD[after[0]] - (after[1].some((d) => d.reserve) ? RESERVE_TAG : 0)
      : Math.min(n.y, r + 1 < rails.length ? rails[r + 1] - 45 : Infinity);
    const lanesTop = gutterTop + (kind === "common" ? FEED_LANE : LANE_PAD);
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
  const commonLanes = common ? common.gutterTop + FEED_LANE : box.y + 120;
  const eh = Math.max(120, commonLanes - INVERTER.gap - INVERTER.top);
  // Над колонкой подписей: низ инвертора выше всех проводов групп
  const external = data.external
    ? { x: box.w + SIDE * 1.2, y: INVERTER.top, w: eh * INVERTER.ratio, h: eh }
    : null;
  const labelX = box.w + FAN;
  const dc = external && data.dc
    ? dcLayout(data.dc, external, Math.max(labelX + LABELS, external.x + external.w) + SIDE) : null;
  // Подписи групп — по порядку проводов сверху вниз: веер без пересечений; ниже инвертора и
  // дорожек щита АКБ
  const groups = placed.filter((p) => p.lane !== null && p.dev.group).sort((a, b) => a.lane! - b.lane!);
  const lo = dc ? Math.max(...dc.lanes) + LABEL_STEP
    : external ? external.y + external.h + LABEL_STEP : box.y + LABEL_STEP / 2;
  fan(groups.map((p) => p.lane!), LABEL_STEP, lo).forEach((y, k) => { groups[k].label = y; });
  const lastLabel = groups.length ? groups[groups.length - 1].label! + LABEL_STEP / 2 : 0;
  const width = Math.max(labelX + LABELS, external ? external.x + external.w + SIDE / 5 : 0,
                         dc ? dc.box.x + dc.box.w + DC_LABEL : 0);
  const height = Math.max(box.y + box.h, lastLabel, dc ? dc.battery.y + dc.battery.h + 14 : 0);
  return { enclosure: enc, perRow, width, height, box, railX, rails, rows, placed, external, labelX,
           pe, n, terminals, dc };
}

const DC_LABEL = 80;  // справа от щита АКБ — подписи строк панелей

// Щит АКБ: дорожки к инвертору под ним, корпус ниже, аппараты на рейках (с бэка — row),
// провода строк панелей под корпусом (у левой строки ниже), АКБ — под автоматом АКБ
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

// Центр клеммы: 0 — вводная, 1… — малые
export function termX(r: Rect, k: number): number {
  return k === 0 ? r.x + TERM.foot + TERM.big / 2 : r.x + TERM.foot + TERM.big + (k - 0.5) * TERM.pitch;
}

// Провод группы: из нижней клеммы вниз в пучок, по пучку в правую стенку, коротко прямо и
// под углом к подписи
export function groupPath(l: PanelLayout, p: Placed): [number, number][] {
  const right = l.box.x + l.box.w, from = p.y + p.h - SCREW;
  const cx = p.x + MODULE / 2;
  const pts: [number, number][] = [[cx, from], [cx, p.lane!], [right + STUB, p.lane!]];
  if (p.label !== null) pts.push([l.labelX - 3, p.label]);
  return pts;
}

// Участки фазной гребёнки над рейкой групп: основная и резервная — отдельно,
// [x0, x1, резерв]; от первого аппарата участка до конца последнего
export function busSegments(row: Placed[]): [number, number, boolean][] {
  const out: [number, number, boolean][] = [];
  for (const reserve of [false, true]) {
    const xs = row.filter((p) => !!p.dev.reserve === reserve && rowKind(p.dev) !== "common");
    if (xs.length) out.push([xs[0].x, xs[xs.length - 1].x + xs[xs.length - 1].w, reserve]);
  }
  return out;
}
