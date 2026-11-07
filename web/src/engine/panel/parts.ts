// Panel hardware in panel mm, no state and no wires: the enclosure, a DIN rail, N / PE terminal
// blocks, the battery cabinet and the hybrid inverter (or generator plug). Devices on the rails
// are catalog.ts; the wires between all of these are painter.ts.

import type { PanelData } from "@/shared/types";
import { shade, text, type Pen } from "./catalog";
import { TERM, termX, type PanelLayout, type Rect } from "./layout";

export const LABEL = 7;     // labels at wires, panel mm
const INSIDE = "#ededeb";  // the enclosure interior is light in any theme, like a real panel

// Enclosure: the panel plastic and the mounting plate inside, the size below it
export function enclosureBox(pen: Pen, b: Rect, enc: PanelLayout["enclosure"]) {
  const { ctx } = pen;
  ctx.fillStyle = enc.body;
  ctx.strokeStyle = pen.ink; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.roundRect(b.x, b.y, b.w, b.h, 8); ctx.fill(); ctx.stroke();
  ctx.fillStyle = INSIDE; ctx.strokeStyle = "#b9b9b5"; ctx.lineWidth = 0.8;
  ctx.beginPath(); ctx.roundRect(b.x + 3, b.y + 3, b.w - 6, b.h - 6, 6); ctx.fill(); ctx.stroke();
  text(pen, `${enc.width} × ${enc.height} мм`, b.x + b.w, b.y + b.h + 7, 5, pen.ink, "right");
}

// TS35 DIN rail: a 35 mm profile with flanges and mounting slots; visible at the ends and in
// the gaps between devices
export function rail(pen: Pen, x0: number, x1: number, y: number) {
  const { ctx } = pen;
  ctx.fillStyle = "#a9a9a6";
  ctx.fillRect(x0, y - 17.5, x1 - x0, 35);
  ctx.fillStyle = "#c9c9c6";
  ctx.fillRect(x0, y - 12.5, x1 - x0, 25);
  ctx.fillStyle = "#8f8f8c";
  for (let x = x0 + 10; x + 18 < x1; x += 50) {
    ctx.beginPath(); ctx.roundRect(x, y - 2.6, 18, 5.2, 2.6); ctx.fill();
  }
}

// N / PE terminal block (like Hager QuickConnect): a light body with mounting feet and a strip
// in the conductor colour; the input terminal takes a screw, the others are screwless: a lever
// in the conductor colour on top, a round wire hole below; a tag on the right
export function terminalBlock(pen: Pen, r: Rect, label: string, color: string, n: number) {
  const { ctx } = pen;
  const x0 = r.x + TERM.foot, x1 = r.x + r.w - TERM.foot;
  // Mounting feet
  for (const x of [r.x, x1]) {
    ctx.fillStyle = "#b5b5b1"; ctx.strokeStyle = "#7d7d79"; ctx.lineWidth = 0.6;
    ctx.beginPath(); ctx.roundRect(x, r.y + 5, TERM.foot, r.h - 10, 1); ctx.fill(); ctx.stroke();
    ctx.fillStyle = "#7d7d79";
    ctx.beginPath(); ctx.arc(x + TERM.foot / 2, r.y + r.h / 2, 1.2, 0, 2 * Math.PI); ctx.fill();
  }
  // Body and a conductor-colour strip along the bottom
  ctx.fillStyle = "#e4e4e0"; ctx.strokeStyle = "#8a8a86"; ctx.lineWidth = 0.8;
  ctx.beginPath(); ctx.roundRect(x0, r.y, x1 - x0, r.h, 2); ctx.fill(); ctx.stroke();
  ctx.fillStyle = "#f3f3f0";
  ctx.fillRect(x0 + 1, r.y + 1, x1 - x0 - 2, 2);
  ctx.fillStyle = color;
  ctx.fillRect(x0 + 1, r.y + r.h - 3.2, x1 - x0 - 2, 2.2);
  // Input terminal: screw and hole
  const big = termX(r, 0);
  ctx.fillStyle = "#d2d2ce";
  ctx.fillRect(big - TERM.big / 2 + 0.6, r.y + 3.5, TERM.big - 1.2, r.h - 8);
  ctx.fillStyle = "#cfcfcb"; ctx.strokeStyle = "#6b6b68"; ctx.lineWidth = 0.5;
  ctx.beginPath(); ctx.arc(big, r.y + 7.5, 3.4, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
  ctx.strokeStyle = "#4a4a48"; ctx.lineWidth = 0.7;
  ctx.beginPath(); ctx.moveTo(big - 2.2, r.y + 7.5); ctx.lineTo(big + 2.2, r.y + 7.5); ctx.stroke();
  ctx.fillStyle = "#26282a";
  ctx.beginPath(); ctx.arc(big, r.y + r.h - 8.5, 2.6, 0, 2 * Math.PI); ctx.fill();
  // Screwless terminals: dividers, lever, hole
  for (let k = 1; k <= n; k++) {
    const cx = termX(r, k);
    ctx.strokeStyle = "#c4c4c0"; ctx.lineWidth = 0.5;
    ctx.beginPath(); ctx.moveTo(cx - TERM.pitch / 2, r.y + 3); ctx.lineTo(cx - TERM.pitch / 2, r.y + r.h - 4); ctx.stroke();
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.roundRect(cx - 1.8, r.y + 3.5, 3.6, 6.5, 0.8); ctx.fill();
    ctx.fillStyle = shade(color, 1.25);
    ctx.fillRect(cx - 1.8, r.y + 3.5, 3.6, 1.2);
    ctx.fillStyle = "#26282a";
    ctx.beginPath(); ctx.arc(cx, r.y + r.h - 8.5, 1.8, 0, 2 * Math.PI); ctx.fill();
  }
  // Marking tag
  const tx = x1 - TERM.tag;
  ctx.fillStyle = color;
  ctx.beginPath(); ctx.roundRect(tx + 1.5, r.y + 4, TERM.tag - 3, r.h - 9, 1); ctx.fill();
  text(pen, label, tx + TERM.tag / 2, r.y + (r.h - 1) / 2, 6, "#ffffff");
}

// Battery: a cabinet with a front panel and a charge indicator
export function batteryCabinet(pen: Pen, r: Rect, data: NonNullable<PanelData["dc"]>, language?: string) {
  const { ctx } = pen, b = data.battery;
  ctx.fillStyle = "#3b4046"; ctx.strokeStyle = "#22262a"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.roundRect(r.x, r.y, r.w, r.h, 5); ctx.fill(); ctx.stroke();
  ctx.fillStyle = "#4a5057";
  ctx.beginPath(); ctx.roundRect(r.x + 8, r.y + 14, r.w - 16, r.h * 0.42, 3); ctx.fill();
  // Charge indicator
  const dx = r.x + 18, dy = r.y + 24, dw = r.w - 36, dh = 16;
  ctx.fillStyle = "#9fd6c8";
  ctx.beginPath(); ctx.roundRect(dx, dy, dw, dh, 2); ctx.fill();
  text(pen, `${b.voltage} V  ▮▮▮▮▯`, dx + dw / 2, dy + dh / 2, 7, "#173b33");
  const v = `${b.voltage} В${b.voltage_assumed ? "*" : ""}`;
  // Old .epd without the unit in texts: use the project language from the manifest
  const kwh = data.texts.kwh ?? (language === "uk" ? "кВт·год" : "кВт·ч");
  const cap = b.capacity ? ` · ${String(b.capacity).replace(".", ",")} ${kwh}` : "";
  text(pen, `${data.texts.battery} ${v}${cap}`, r.x + r.w / 2, r.y + r.h * 0.42 + 2, 6.5, "#e8e8e6");
  // Ribs on the lower part
  ctx.strokeStyle = "#2d3136"; ctx.lineWidth = 1;
  for (let y = r.y + r.h * 0.62; y < r.y + r.h - 8; y += 9) {
    ctx.beginPath(); ctx.moveTo(r.x + 10, y); ctx.lineTo(r.x + r.w - 10, y); ctx.stroke();
  }
}

// Hybrid inverter (looks like 5 kW wall-mounted units): a light body with heatsink ribs on the
// sides, a dark front panel with a display, indicators and buttons, at the bottom the battery
// and PV inputs (glands) and LOAD, GRID, PE terminals. A generator plug is the same body
// without GRID. Returns the terminal x positions
export function inverterBody(pen: Pen, e: Rect, x: NonNullable<PanelData["external"]>) {
  const { ctx } = pen, w = e.w, h = e.h;
  const inverter = x.kind === "inverter";
  text(pen, `${x.id} · ${x.title}`, e.x, e.y - 5, LABEL, pen.ink, "left");
  // Body and heatsink ribs
  ctx.fillStyle = "#f2f3f1"; ctx.strokeStyle = "#8a8a86"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.roundRect(e.x, e.y, w, h, 6); ctx.fill(); ctx.stroke();
  const fin = w * 0.07;
  ctx.fillStyle = "#c9cbc8";
  for (const fx of [e.x + 2, e.x + w - fin - 2]) {
    ctx.fillRect(fx, e.y + h * 0.06, fin, h * 0.74);
    ctx.strokeStyle = "#a3a5a2"; ctx.lineWidth = 0.6;
    for (let fy = e.y + h * 0.08; fy < e.y + h * 0.79; fy += h * 0.025) {
      ctx.beginPath(); ctx.moveTo(fx, fy); ctx.lineTo(fx + fin, fy); ctx.stroke();
    }
  }
  // Front panel
  const px = e.x + w * 0.14, pw = w * 0.72, py = e.y + h * 0.1, ph = h * 0.36;
  ctx.fillStyle = "#2a2d31";
  ctx.beginPath(); ctx.roundRect(px, py, pw, ph, 5); ctx.fill();
  // Display
  const dx = px + pw * 0.1, dw = pw * 0.8, dy = py + ph * 0.1, dh = ph * 0.36;
  ctx.fillStyle = "#9fd6c8";
  ctx.beginPath(); ctx.roundRect(dx, dy, dw, dh, 2); ctx.fill();
  const fs = dh * 0.28;
  text(pen, inverter ? "230V  50Hz" : (x.kind === "station" ? "STATION 230V" : "GEN 230V"), dx + dw / 2, dy + dh * 0.32, fs, "#173b33");
  text(pen, inverter ? "5.0 kW  ▮▮▮▯ 76%" : "STANDBY", dx + dw / 2, dy + dh * 0.7, fs * 0.9, "#173b33");
  // Indicators: DC, AC, normal, fault
  const leds = ["#3ecf5a", "#3ecf5a", "#3ecf5a", "#5a2a2a"];
  leds.forEach((c, k) => {
    const lx = dx + dw * (0.12 + k * 0.25), ly = dy + dh + ph * 0.12;
    ctx.fillStyle = c;
    ctx.beginPath(); ctx.arc(lx, ly, Math.max(1.6, ph * 0.035), 0, 2 * Math.PI); ctx.fill();
  });
  // Buttons
  for (let k = 0; k < 4; k++) {
    const bx = dx + dw * (0.12 + k * 0.25), by = dy + dh + ph * 0.32;
    ctx.fillStyle = "#4a4f55";
    ctx.beginPath(); ctx.roundRect(bx - pw * 0.06, by - ph * 0.05, pw * 0.12, ph * 0.1, 1.5); ctx.fill();
  }
  text(pen, inverter ? "HYBRID INVERTER" : "POWER INLET", e.x + w / 2, py + ph + h * 0.05, h * 0.022, "#7a7d80");
  // Bottom connection panel
  const cy = e.y + h * 0.84, ch = h * 0.13;
  ctx.fillStyle = "#3a3d42";
  ctx.beginPath(); ctx.roundRect(e.x + w * 0.04, cy, w * 0.92, ch, 3); ctx.fill();
  // Battery and PV inputs on the right go to the battery box (further right), grid terminals on the left go to the panel
  const glands = inverter ? ["BAT+", "BAT−", "PV1", "PV2"] : [];
  const gxs = glands.map((_, k) => e.x + w * (0.6 + k * 0.085 + (k >= 2 ? 0.04 : 0)));
  glands.forEach((g, k) => {
    const gx = gxs[k], gy = cy + ch * 0.45;
    ctx.fillStyle = "#16181b";
    ctx.beginPath(); ctx.arc(gx, gy, w * 0.026, 0, 2 * Math.PI); ctx.fill();
    text(pen, g, gx, cy + ch * 0.85, ch * 0.13, "#c9ccd0");
  });
  // Terminals: LOAD L N, GRID L N, PE
  const pitch = w * 0.085, x0 = e.x + w * 0.1;
  const names = inverter ? ["L", "N", "L", "N", "PE"] : ["L", "N", "PE"];
  const xs = names.map((_, k) => x0 + k * pitch + (inverter && k >= 2 ? pitch * 0.3 : 0) + (k === names.length - 1 ? pitch * 0.3 : 0));
  names.forEach((n, k) => {
    ctx.fillStyle = "#d4d4d0";
    ctx.beginPath(); ctx.roundRect(xs[k] - pitch * 0.38, cy + ch * 0.35, pitch * 0.76, ch * 0.45, 1); ctx.fill();
    ctx.fillStyle = "#6b6b68";
    ctx.beginPath(); ctx.arc(xs[k], cy + ch * 0.57, pitch * 0.18, 0, 2 * Math.PI); ctx.fill();
    text(pen, n, xs[k], cy + ch * 0.92, ch * 0.13, "#e8e8e6");
  });
  const tag = (a: number, b: number, s: string) => text(pen, s, (xs[a] + xs[b]) / 2, cy + ch * 0.17, ch * 0.13, "#c9ccd0");
  tag(0, 1, "LOAD");
  if (inverter) tag(2, 3, "GRID");
  return {
    loadL: xs[0], loadN: xs[1],
    gridL: inverter ? xs[2] : null, gridN: inverter ? xs[3] : null,
    pe: xs[xs.length - 1],
    glands: inverter ? { bat: [gxs[0], gxs[1]] as [number, number], pv: [gxs[2], gxs[3]] } : null,
  };
}
