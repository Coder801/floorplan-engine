// Раскладка щита в лицо, мм щита (ось Y вниз). Рейки по видам аппаратов: вверху — общие
// (ввод, реле, ПЗІП, АВР, питание инвертора), ниже — автоматы на однополюсной гребёнке,
// ещё ниже — дифавтоматы на двойной (L + N); вид, что не влез в рейку, продолжается на
// следующей. Основная и резервная гребёнки — участками одной рейки. Аппарат — серединой
// на оси рейки (DIN 43880), ширина — из модели каталога. Питание сверху (гребёнка над
// аппаратами), группы — из нижних клемм вниз, в свою дорожку под рейкой и вправо из
// корпуса к подписям: у левого аппарата дорожка ниже, провода групп не пересекаются.
// Вверху корпуса — клеммник PE, внизу — N. Чистые функции — без canvas, с тестами.

import type { PanelData, PanelDevice } from "@/shared/types";

export const MODULE = 17.5;     // ширина модуля DIN, мм
export const LANE = 13;         // шаг дорожек групп под рейкой: кабель из трёх жил (PE, L, N)
export const LANE_PAD = 10;     // от низа аппарата до верхней дорожки
export const COMMON_GAP = 40;   // под общими аппаратами: перемычки и питание гребёнок
export const HEAD = { common: 16, single: 20, double: 26 } as const;  // над аппаратами: гребёнки и подход резерва
export const LABELS = 320;      // колонка подписей групп справа от корпуса
export const PAD = 38;          // от стенки щита до рейки: у стенки — ввод N и питание гребёнок
export const LEAD = 60;         // ввод над щитом
export const SIDE = 50;         // от корпуса до инвертора или вилки — просвет для его проводов
// Инвертор — пропорции гибридного на 5 кВт (330 × 580 мм); высота — от верха чертежа до
// дорожек общей рейки: его провода приходят снизу и не пересекают подписи
export const INVERTER = { top: 10, ratio: 330 / 580, gap: 16 } as const;
export const ROWS = [12, 18, 24] as const;  // модулей в рейке
export const BUS = 30;          // полоса клеммника PE (вверху) и N (внизу)
export const BUS_X = 8;         // от стенки щита до клеммника
// Клеммник N / PE в корпусе (как Hager QuickConnect): лапка, вводная клемма под винт, ряд
// безвинтовых клемм, бирка, лапка
export const TERM = { h: 22, foot: 5, big: 12, pitch: 7, tag: 14 } as const;

// Общие аппараты — в порядке на рейке; питание основной сети идёт ввод → реле, резервной —
// от АВР (или переключателя)
const COMMON = ["input", "relay", "spd", "changeover", "ats", "feed"];
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
  lane: number | null;  // y дорожки провода группы или питания инвертора; нет — null
}

export interface Row {
  kind: RowKind;
  top: number;          // верх ряда (гребёнки над аппаратами)
  devTop: number;       // верх аппаратов
  devH: number;         // высота самого высокого аппарата; ось рейки — devTop + devH / 2
  gutterTop: number;    // низ аппаратов
  gutterBottom: number; // низ ряда (под дорожками)
}

export interface PanelLayout {
  perRow: number;
  width: number;        // всё вместе: ввод, щит, подписи, внешний аппарат
  height: number;
  box: Rect;            // корпус щита
  rows: Row[];
  placed: Placed[];
  external: Rect | null;
  pe: Rect;             // клеммник PE
  n: Rect;              // клеммник N
  terminals: number;    // малых клемм в клеммнике
}

// Рейки по видам: общие, автоматы, дифавтоматы; внутри вида — порядок данных (основные,
// потом резервные), общие — в порядке COMMON; аппарат не делится между рейками
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

export function layout(data: PanelData, perRow: number): PanelLayout {
  const split = splitRows(data.devices, perRow);
  const boxW = perRow * MODULE + 2 * PAD;
  const rows: Row[] = [];
  const placed: Placed[] = [];
  let y = LEAD + PAD + BUS;
  // Своя дорожка — у групп и у питания внешнего аппарата (инвертора)
  const out = (d: PanelDevice) => !!d.group || d.id === data.external?.feed;
  split.forEach(([kind, devs], r) => {
    const devH = Math.max(...devs.map((d) => d.model.height), 0);
    const devTop = y + HEAD[kind];
    const gutterTop = devTop + devH;
    const lanesTop = gutterTop + (kind === "common" ? COMMON_GAP : LANE_PAD);
    const lanes = devs.filter(out).length;
    const gutterBottom = lanesTop + lanes * LANE + (kind === "common" && !lanes ? 0 : LANE_PAD);
    rows.push({ kind, top: y, devTop, devH, gutterTop, gutterBottom });
    let x = PAD, k = lanes;
    for (const d of devs) {
      const lane = out(d) ? lanesTop + --k * LANE : null;
      placed.push({ dev: d, row: r, lane, x, y: devTop + (devH - d.model.height) / 2, w: d.model.width,
                    h: d.model.height });
      x += d.model.width;
    }
    y = gutterBottom;
  });
  const box = { x: 0, y: LEAD, w: boxW, h: y + BUS + PAD - LEAD };
  // Клемм — по группе, вводу и запасу; длина по числу клемм, но не больше корпуса;
  // оба клеммника — по центру корпуса
  const room = boxW - 2 * BUS_X;
  const terminals = Math.max(2, Math.min(Object.keys(data.groups).length + 2,
                                         Math.floor((room - termWidth(0)) / TERM.pitch)));
  const tw = termWidth(terminals);
  const bar = (x: number, by: number) => ({ x, y: by - TERM.h / 2, w: tw, h: TERM.h });
  const common = rows.find((r) => r.kind === "common");
  const lanesTop = common ? common.gutterTop + COMMON_GAP : LEAD + PAD + BUS + 120;
  const eh = Math.max(120, lanesTop - INVERTER.gap - INVERTER.top);
  // Над колонкой подписей: низ инвертора выше всех дорожек групп
  const external = data.external
    ? { x: boxW + SIDE * 1.2, y: INVERTER.top, w: eh * INVERTER.ratio, h: eh }
    : null;
  const width = Math.max(boxW + LABELS, external ? external.x + external.w + SIDE / 5 : 0);
  return { perRow, width, height: box.y + box.h, box, rows, placed, external,
           pe: bar((boxW - tw) / 2, LEAD + PAD / 2 + BUS / 2), n: bar((boxW - tw) / 2, y + BUS / 2 + PAD / 2),
           terminals };
}

export function termWidth(n: number): number {
  return 2 * TERM.foot + TERM.big + n * TERM.pitch + TERM.tag;
}

// Центр клеммы: 0 — вводная, 1… — малые
export function termX(r: Rect, k: number): number {
  return k === 0 ? r.x + TERM.foot + TERM.big / 2 : r.x + TERM.foot + TERM.big + (k - 0.5) * TERM.pitch;
}

// Ширина рейки, при которой щит крупнее всего в окне w × h (px)
export function bestLayout(data: PanelData, w: number, h: number): PanelLayout {
  let best: PanelLayout | null = null, bestK = -1;
  for (const n of ROWS) {
    const l = layout(data, n);
    const k = Math.min(w / l.width, h / l.height);
    if (k > bestK + 1e-9) { best = l; bestK = k; }
  }
  return best!;
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
