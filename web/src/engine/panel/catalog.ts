// Отрисовщики аппаратов по модели каталога (panel_catalog.py): сначала свой для
// «бренд.вид» (generic.breaker), потом общий по виду (style), потом прямоугольник.
// Новый бренд с другим видом лицевой панели — свой отрисовщик здесь же.

import type { PanelDevice } from "@/shared/types";
import type { Rect } from "./layout";

export interface Pen {
  ctx: CanvasRenderingContext2D;
  font: string;     // семейство шрифта страницы
  ink: string;      // цвет линий и текста по теме
}

export type Renderer = (pen: Pen, d: PanelDevice, r: Rect) => void;

const M = 17.5;

export function text(pen: Pen, s: string, x: number, y: number, size: number,
                     color = "#2b2b2b", align: CanvasTextAlign = "center") {
  const { ctx } = pen;
  ctx.fillStyle = color;
  ctx.font = `${size}px ${pen.font}`;
  ctx.textAlign = align;
  ctx.textBaseline = "middle";
  ctx.fillText(s, x, y);
}

// Строка, обрезанная с «…» под ширину, мм
export function clip(pen: Pen, s: string, width: number, size: number): string {
  const { ctx } = pen;
  ctx.font = `${size}px ${pen.font}`;
  if (ctx.measureText(s).width <= width) return s;
  while (s && ctx.measureText(s + "…").width > width) s = s.slice(0, -1);
  return s.trimEnd() + "…";
}

// Габарит модульного аппарата (DIN 43880): лицевая крышка 45 мм по центру — на оси
// рейки, над и под ней — клеммные зоны с винтами, по винту на модуль
export const FRONT = 45;
export const SCREW = 9;         // от края аппарата до центра винта клеммы
const SCREW_R = 3.6;
export const PLATE = { y: 2, h: 6.5 };  // маркировочная табличка от верха крышки: обозначение

export const shade = (hex: string, k: number) => {
  const n = parseInt(hex.slice(1), 16);
  const c = (v: number) => Math.round(Math.min(255, Math.max(0, v * k)));
  return `rgb(${c(n >> 16)},${c((n >> 8) & 255)},${c(n & 255)})`;
};

// Центр лицевой крышки
const mid = (r: Rect) => r.y + r.h / 2;

function screw(pen: Pen, x: number, y: number) {
  const { ctx } = pen;
  ctx.fillStyle = "#d4d4d0";
  ctx.strokeStyle = "#6b6b68";
  ctx.lineWidth = 0.6;
  ctx.beginPath(); ctx.arc(x, y, SCREW_R + 1.2, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
  ctx.fillStyle = "#9c9c98";
  ctx.beginPath(); ctx.arc(x, y, SCREW_R, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
  // Шлиц «+»
  ctx.strokeStyle = "#4a4a48"; ctx.lineWidth = 0.9;
  ctx.beginPath();
  ctx.moveTo(x - 2.4, y); ctx.lineTo(x + 2.4, y);
  ctx.moveTo(x, y - 2.4); ctx.lineTo(x, y + 2.4);
  ctx.stroke();
}

// Винты клемм: top / bottom — сколько модулей с винтом (по умолчанию — все)
export function plate(r: Rect): Rect {
  return { x: r.x + 2, y: mid(r) - FRONT / 2 + PLATE.y, w: r.w - 4, h: PLATE.h };
}

export function screwsX(r: Rect, n = Math.round(r.w / M)): number[] {
  return Array.from({ length: n }, (_, k) => r.x + (k + 0.5) * (r.w / n));
}

function body(pen: Pen, d: PanelDevice, r: Rect, bottom?: number) {
  const { ctx } = pen;
  const base = d.model.body;
  // Клеммные зоны — корпус ниже крышки, чуть темнее
  ctx.fillStyle = shade(base, 0.93);
  ctx.strokeStyle = "#6b6b68";
  ctx.lineWidth = 0.7;
  ctx.beginPath(); ctx.roundRect(r.x + 0.4, r.y, r.w - 0.8, r.h, 2); ctx.fill(); ctx.stroke();
  // Лицевая крышка с тенью снизу
  const f = { x: r.x + 0.4, y: mid(r) - FRONT / 2, w: r.w - 0.8, h: FRONT };
  ctx.fillStyle = shade(base, 0.8);
  ctx.fillRect(f.x, f.y + f.h, f.w, 1.6);
  ctx.fillStyle = base;
  ctx.fillRect(f.x, f.y, f.w, f.h);
  ctx.strokeRect(f.x, f.y, f.w, f.h);
  // Стыки модулей у многополюсных — тонкой линией
  const n = Math.round(r.w / M);
  ctx.strokeStyle = shade(base, 0.82); ctx.lineWidth = 0.4;
  for (let k = 1; k < n; k++) {
    const x = r.x + k * (r.w / n);
    ctx.beginPath(); ctx.moveTo(x, r.y + 2); ctx.lineTo(x, r.y + r.h - 2); ctx.stroke();
  }
  for (const x of screwsX(r)) screw(pen, x, r.y + SCREW);
  for (const x of screwsX(r, bottom)) screw(pen, x, r.y + r.h - SCREW);
  ctx.fillStyle = shade(base, 0.88);
  ctx.fillRect(f.x + 1.6, f.y + PLATE.y, f.w - 3.2, PLATE.h);
}

// Рычаг в пазу, положение «вкл» (вверх), и зелёный флажок справа внизу
function lever(pen: Pen, d: PanelDevice, cx: number, cy: number) {
  const { ctx } = pen;
  ctx.fillStyle = "#3c3c3a";
  ctx.beginPath(); ctx.roundRect(cx - 4, cy - 10, 8, 20, 1.2); ctx.fill();
  ctx.fillStyle = d.model.lever;
  ctx.beginPath(); ctx.roundRect(cx - 3.2, cy - 9.5, 6.4, 11, 1); ctx.fill();
  ctx.fillStyle = shade("#808080", 1.2);
  ctx.fillRect(cx - 3.2, cy - 9.5, 6.4, 1.6);
  ctx.fillStyle = "#2e9e44";
  ctx.fillRect(cx + 1, cy + 11.5, 4, 2.2);
}

// Номинал на крышке: «C16» крупно, остальное («30 мА», «2P») мельче строкой ниже
function rating(pen: Pen, d: PanelDevice, r: Rect, cx = r.x + r.w / 2) {
  const [head, ...rest] = d.label.split(" ");
  const y = mid(r) + FRONT / 2 - (rest.length ? 9 : 6);
  text(pen, clip(pen, head, r.w - 2, 6.5), cx, y, 6.5, "#1e1e1e");
  if (rest.length) text(pen, clip(pen, rest.join(" "), r.w - 2, 4.2), cx, y + 5.5, 4.2, "#3a3a3a");
}

function test(pen: Pen, d: PanelDevice, cx: number, cy: number) {
  const { ctx } = pen;
  ctx.fillStyle = shade(d.model.accent || "#3a6ea5", 0.85);
  ctx.beginPath(); ctx.arc(cx, cy, 4.4, 0, 2 * Math.PI); ctx.fill();
  ctx.fillStyle = d.model.accent || "#3a6ea5";
  ctx.beginPath(); ctx.arc(cx, cy - 0.4, 3.8, 0, 2 * Math.PI); ctx.fill();
  text(pen, "T", cx, cy - 0.4, 4.2, "#fff");
}

// Окно индикатора: тёмное стекло с цифрами
function display(pen: Pen, x: number, y: number, w: number, h: number, s: string, color: string) {
  const { ctx } = pen;
  ctx.fillStyle = "#1b1f1c";
  ctx.beginPath(); ctx.roundRect(x, y, w, h, 1.2); ctx.fill();
  text(pen, s, x + w / 2, y + h / 2 + 0.3, h * 0.62, color);
}

const levers = (n: number): Renderer => (pen, d, r) => {
  body(pen, d, r);
  for (let k = 0; k < n; k++) lever(pen, d, r.x + (k + 0.5) * (r.w / n), mid(r) - 2);
  rating(pen, d, r);
};

// Дифавтомат и УЗО: рычаг в первом модуле, кнопка «Тест» во втором
const withTest: Renderer = (pen, d, r) => {
  body(pen, d, r);
  lever(pen, d, r.x + M / 2, mid(r) - 2);
  test(pen, d, r.x + r.w - M / 2, mid(r) - 7);
  rating(pen, d, r, r.x + r.w - M / 2 - 1);
};

const RENDERERS: Record<string, Renderer> = {
  breaker: levers(1),
  input: levers(2),
  feed: levers(2),
  diff: withTest,
  rcd: withTest,
  relay: (pen, d, r) => {
    body(pen, d, r);
    const { ctx } = pen, y = mid(r) - FRONT / 2;
    display(pen, r.x + 5, y + 11, r.w - 18, 11, "230", "#ff5a3c");
    // Кнопки настройки справа от окна
    ctx.fillStyle = "#9a9a96";
    for (let k = 0; k < 3; k++) {
      ctx.beginPath(); ctx.arc(r.x + r.w - 7, y + 12 + k * 5, 1.7, 0, 2 * Math.PI); ctx.fill();
    }
    text(pen, "V", r.x + r.w - 11.5, y + 16.5, 3.5, "#444");
    rating(pen, d, r);
  },
  spd: (pen, d, r) => {
    body(pen, d, r, 1);  // снизу — одна клемма PE
    const { ctx } = pen, y = mid(r) - FRONT / 2 + 10;
    // Сменные вставки с окном исправности
    for (const x of screwsX(r)) {
      ctx.fillStyle = "#e2e2de"; ctx.strokeStyle = "#7a7a76"; ctx.lineWidth = 0.6;
      ctx.beginPath(); ctx.roundRect(x - 7, y, 14, 22, 1.5); ctx.fill(); ctx.stroke();
      ctx.fillStyle = "#2e9e44"; ctx.fillRect(x - 3, y + 3, 6, 3);
      text(pen, "⚡", x, y + 13, 6, "#c98a00");
    }
    rating(pen, d, r);
  },
  changeover: (pen, d, r) => {
    body(pen, d, r);
    const { ctx } = pen;
    const cx = r.x + r.w / 2, cy = mid(r);
    text(pen, "I", cx - 16, cy + 4, 4.5, "#1e1e1e");
    text(pen, "0", cx - 16, cy - 4, 4.5, "#1e1e1e");
    text(pen, "II", cx + 16, cy, 4.5, "#1e1e1e");
    ctx.fillStyle = "#3c3c3a";
    ctx.beginPath(); ctx.arc(cx, cy, 11, 0, 2 * Math.PI); ctx.fill();
    ctx.fillStyle = "#c62828";
    ctx.beginPath(); ctx.arc(cx, cy, 9.5, 0, 2 * Math.PI); ctx.fill();
    ctx.fillStyle = "#fbe9e7"; ctx.fillRect(cx - 2, cy - 9, 4, 18);
    rating(pen, d, r);
  },
  ats: (pen, d, r) => {
    body(pen, d, r);
    const { ctx } = pen, y = mid(r) - FRONT / 2;
    display(pen, r.x + 6, y + 10, r.w - 12, 10, "ATS", "#ffd54f");
    // Индикаторы источников I и II
    [["#2e9e44", "I"], ["#9a9a96", "II"]].forEach(([c, s], k) => {
      const x = r.x + r.w / 2 + (k ? 10 : -10);
      ctx.fillStyle = c;
      ctx.beginPath(); ctx.arc(x, y + 26, 2, 0, 2 * Math.PI); ctx.fill();
      text(pen, s, x + 5, y + 26, 3.8, "#333", "left");
    });
    rating(pen, d, r);
  },
};

const fallback: Renderer = (pen, d, r) => { body(pen, d, r); rating(pen, d, r); };

export function rendererFor(d: PanelDevice): Renderer {
  return RENDERERS[`${d.model.brand}.${d.model.style}`] || RENDERERS[d.model.style] || fallback;
}
