// Device renderers by catalogue model (panel_catalog.py): first a specific one for
// "brand.kind" (generic.breaker), then a shared one by kind (style), then a rectangle.
// A new brand with a different front panel gets its own renderer right here.

import type { PanelDevice } from "@/shared/types";
import type { Rect } from "./layout";

export interface Pen {
  ctx: CanvasRenderingContext2D;
  font: string;     // page font family
  ink: string;      // line and text colour for the theme
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

// String cut with "…" to fit the width, mm
export function clip(pen: Pen, s: string, width: number, size: number): string {
  const { ctx } = pen;
  ctx.font = `${size}px ${pen.font}`;
  if (ctx.measureText(s).width <= width) return s;
  while (s && ctx.measureText(s + "…").width > width) s = s.slice(0, -1);
  return s.trimEnd() + "…";
}

// Modular device size (DIN 43880): a 45 mm front cover centred on the rail axis, terminal zones
// with screws above and below it, one screw per module
export const FRONT = 45;
export const SCREW = 9;         // from the device edge to the terminal screw centre
const SCREW_R = 3.6;
export const PLATE = { y: 2, h: 6.5 };  // marking plate from the top of the cover: designation

export const shade = (hex: string, k: number) => {
  const n = parseInt(hex.slice(1), 16);
  const c = (v: number) => Math.round(Math.min(255, Math.max(0, v * k)));
  return `rgb(${c(n >> 16)},${c((n >> 8) & 255)},${c(n & 255)})`;
};

// Front cover centre
const mid = (r: Rect) => r.y + r.h / 2;

function screw(pen: Pen, x: number, y: number) {
  const { ctx } = pen;
  ctx.fillStyle = "#d4d4d0";
  ctx.strokeStyle = "#6b6b68";
  ctx.lineWidth = 0.6;
  ctx.beginPath(); ctx.arc(x, y, SCREW_R + 1.2, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
  ctx.fillStyle = "#9c9c98";
  ctx.beginPath(); ctx.arc(x, y, SCREW_R, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
  // "+" slot
  ctx.strokeStyle = "#4a4a48"; ctx.lineWidth = 0.9;
  ctx.beginPath();
  ctx.moveTo(x - 2.4, y); ctx.lineTo(x + 2.4, y);
  ctx.moveTo(x, y - 2.4); ctx.lineTo(x, y + 2.4);
  ctx.stroke();
}

// Terminal screws: top / bottom is how many modules have a screw (all by default)
export function plate(r: Rect): Rect {
  return { x: r.x + 2, y: mid(r) - FRONT / 2 + PLATE.y, w: r.w - 4, h: PLATE.h };
}

export function screwsX(r: Rect, n = Math.round(r.w / M)): number[] {
  return Array.from({ length: n }, (_, k) => r.x + (k + 0.5) * (r.w / n));
}

function body(pen: Pen, d: PanelDevice, r: Rect, bottom?: number) {
  const { ctx } = pen;
  const base = d.model.body;
  // Terminal zones: the body below the cover, slightly darker
  ctx.fillStyle = shade(base, 0.93);
  ctx.strokeStyle = "#6b6b68";
  ctx.lineWidth = 0.7;
  ctx.beginPath(); ctx.roundRect(r.x + 0.4, r.y, r.w - 0.8, r.h, 2); ctx.fill(); ctx.stroke();
  // Front cover with a shadow below
  const f = { x: r.x + 0.4, y: mid(r) - FRONT / 2, w: r.w - 0.8, h: FRONT };
  ctx.fillStyle = shade(base, 0.8);
  ctx.fillRect(f.x, f.y + f.h, f.w, 1.6);
  ctx.fillStyle = base;
  ctx.fillRect(f.x, f.y, f.w, f.h);
  ctx.strokeRect(f.x, f.y, f.w, f.h);
  // Module seams on multi-pole devices as a thin line
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

// Lever in its slot, "on" position (up), and a green flag at the bottom right
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

// Rating on the cover: "C16" large, the rest ("30 мА", "2P") smaller on the line below
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

// Indicator window: dark glass with digits
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

// RCBO and RCD: lever in the first module, "Test" button in the second
const withTest: Renderer = (pen, d, r) => {
  body(pen, d, r);
  lever(pen, d, r.x + M / 2, mid(r) - 2);
  test(pen, d, r.x + r.w - M / 2, mid(r) - 7);
  rating(pen, d, r, r.x + r.w - M / 2 - 1);
};

// A lever per module: 1P breaker, 2P main switch, 3P breaker, 3P+N main switch
const poles: Renderer = (pen, d, r) => levers(Math.max(1, Math.round(r.w / M)))(pen, d, r);

const RENDERERS: Record<string, Renderer> = {
  breaker: poles,
  input: poles,
  feed: levers(2),
  output: levers(2),
  diff: withTest,
  rcd: withTest,
  relay: (pen, d, r) => {
    body(pen, d, r);
    const { ctx } = pen, y = mid(r) - FRONT / 2;
    display(pen, r.x + 5, y + 11, r.w - 18, 11, "230", "#ff5a3c");
    // Setting buttons right of the window
    ctx.fillStyle = "#9a9a96";
    for (let k = 0; k < 3; k++) {
      ctx.beginPath(); ctx.arc(r.x + r.w - 7, y + 12 + k * 5, 1.7, 0, 2 * Math.PI); ctx.fill();
    }
    text(pen, "V", r.x + r.w - 11.5, y + 16.5, 3.5, "#444");
    rating(pen, d, r);
  },
  spd: (pen, d, r) => {
    body(pen, d, r, 1);  // one PE terminal at the bottom
    const { ctx } = pen, y = mid(r) - FRONT / 2 + 10;
    // Replaceable inserts with a status window
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
    // Source I and II indicators
    [["#2e9e44", "I"], ["#9a9a96", "II"]].forEach(([c, s], k) => {
      const x = r.x + r.w / 2 + (k ? 10 : -10);
      ctx.fillStyle = c;
      ctx.beginPath(); ctx.arc(x, y + 26, 2, 0, 2 * Math.PI); ctx.fill();
      text(pen, s, x + 5, y + 26, 3.8, "#333", "left");
    });
    rating(pen, d, r);
  },
};

// Modular contactor of the master switch: a window with "KM" and the coil terminals A1, A2
RENDERERS.contactor = (pen, d, r) => {
  body(pen, d, r);
  const y = mid(r) - FRONT / 2;
  display(pen, r.x + 4, y + 10, r.w - 8, 10, "KM", "#ffb74d");
  text(pen, "A1   A2", r.x + r.w / 2, y + 26, 3.6, "#333");
  rating(pen, d, r);
};

// Battery box DC devices: a red strip along the bottom of the cover (rating "125 А DC 2P"),
// so they are not mistaken for grid breakers
const dc = (inner: Renderer): Renderer => (pen, d, r) => {
  inner(pen, d, r);
  pen.ctx.fillStyle = d.model.accent || "#c62828";
  pen.ctx.fillRect(r.x + 2, mid(r) + FRONT / 2 - 1.8, r.w - 4, 1.4);
};
RENDERERS.dc_battery = dc(levers(2));
RENDERERS.dc_breaker = dc(levers(2));
RENDERERS.dc_spd = RENDERERS.spd;

// LED supply 230 → 12 V on a DIN rail (LED box under the panel): a dark window with the output
// voltage, a green power light, the rating ("100 Вт 12 В") and a yellow strip along the bottom
RENDERERS.led_psu_din = (pen, d, r) => {
  body(pen, d, r);
  const { ctx } = pen, y = mid(r) - FRONT / 2;
  display(pen, r.x + 2.5, y + 10, r.w - 5, 9, r.w > 30 ? "12V DC" : "12V", "#ffd54f");
  ctx.fillStyle = "#2e9e44";
  ctx.beginPath(); ctx.arc(r.x + r.w - 5, y + 24, 1.4, 0, 2 * Math.PI); ctx.fill();
  rating(pen, d, r);
  ctx.fillStyle = d.model.accent || "#f2b705";
  ctx.fillRect(r.x + 2, mid(r) + FRONT / 2 - 1.8, r.w - 4, 1.4);
};

const fallback: Renderer = (pen, d, r) => { body(pen, d, r); rating(pen, d, r); };

export function rendererFor(d: PanelDevice): Renderer {
  return RENDERERS[`${d.model.brand}.${d.model.style}`] || RENDERERS[d.model.style] || fallback;
}
