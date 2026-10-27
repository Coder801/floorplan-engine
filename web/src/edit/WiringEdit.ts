// Правки проводки на листе: линии (участки) и распаечные коробки. Потребители и щит стоят
// на месте. Сохраняются в wiring.yaml проекта (POST /wiring), затем проект пересобирается.

import {
  CABLE_MIN_PX, FLOW_DASH_PX, FLOW_GAP_PX, FLOW_SPEED_PX, FLOW_WIDTH_PX, MIN_LINE_PX, REDUCED_MOTION,
} from "../consts";
import { palette, screenColor } from "../palette";
import type { DrawItem } from "../sheet/paint";
import type { EditBox, EditWire, Page, XY } from "../types";
import { clamp, dragPath, isH, moveEnd, samePt, segDistance, simplifyPath, snap } from "./geometry";

interface Wire extends EditWire { orig: XY[]; keep: boolean; reset: boolean }
interface WBox extends EditBox { orig: XY; reset: boolean }

export type Hit = { kind: "seg"; id: string; i: number } | { kind: "box"; id: string };

type Drag =
  | { kind: "seg"; sx: number; sy: number; parts: Map<string, { path: XY[]; segs: Set<number> }>;
      dx: number; dy: number; moved: boolean }
  | { kind: "box"; id: string; sx: number; sy: number; at: XY;
      wires: { id: string; atStart: boolean; path: XY[] }[]; moved: boolean };

interface Snapshot {
  wires: [string, XY[], boolean, boolean][];
  boxes: [string, XY, boolean][];
}

const copy = (path: XY[]): XY[] => path.map((p) => [p[0], p[1]]);

export class WiringEdit {
  readonly k: number; readonly tx: number; readonly ty: number;
  readonly wires = new Map<string, Wire>();
  readonly boxes = new Map<string, WBox>();
  readonly style = new Map<string, DrawItem>();  // линия → её обводка на листе: цвет, толщина, слой
  sel = new Set<string>();      // выделенные участки «wire_1#2»
  box: string | null = null;    // коробка, по которой кликнули последней
  hover: Hit | null = null;     // что под курсором
  drag: Drag | null = null;
  history: Snapshot[] = [];

  constructor(page: Page, items: DrawItem[], private readonly hidden: () => Set<string>) {
    [this.k, this.tx, this.ty] = page.model!;
    // Правится то, что видно: линия в своей полосе пучка (lane), концы — в узлах щита,
    // коробки и точки; полоса сдвинута поперёк участка, поэтому отвод к узлу — под 90°
    const shown = (w: EditWire) => (w.lane ? simplifyPath([w.path[0], ...w.lane, w.path[w.path.length - 1]]) : w.path);
    for (const [id, w] of Object.entries(page.edit!.wires)) {
      this.wires.set(id, { ...w, orig: copy(shown(w)), path: copy(shown(w)), keep: false, reset: false });
    }
    for (const [id, b] of Object.entries(page.edit!.boxes)) {
      this.boxes.set(id, { ...b, orig: [b.at[0], b.at[1]], at: [b.at[0], b.at[1]], reset: false });
    }
    for (const it of items) {
      if (it.k !== "s" || !it.o || !it.o.startsWith("wire:") || !it.l.startsWith("W-CABLE")) continue;
      const id = it.o.slice(5);
      if (!this.style.has(id)) this.style.set(id, it);
    }
  }

  toSheet(p: XY): XY { return [this.k * p[0] + this.tx, this.ty - this.k * p[1]]; }

  changed(w: Wire) { return w.path.length !== w.orig.length || w.path.some((p, i) => !samePt(p, w.orig[i])); }

  moved(b: WBox) { return !samePt(b.at, b.orig); }

  // Узел подключения коробки (откуда идут её линии) и середина квадрата
  node(b: WBox, at: XY = b.at): XY {
    return b.inward ? [at[0] + b.inward[0] * b.size, at[1] + b.inward[1] * b.size] : at;
  }

  center(b: WBox): XY {
    return b.inward ? [b.at[0] + (b.inward[0] * b.size) / 2, b.at[1] + (b.inward[1] * b.size) / 2] : b.at;
  }

  // Примитивы листа, вместо которых рисуется правка
  hiddenKeys(): Set<string> {
    const out = new Set<string>();
    for (const [id, w] of this.wires) if (this.changed(w)) out.add(`wire:${id}`);
    for (const [id, b] of this.boxes) if (this.moved(b)) out.add(`box:${id}`);
    return out;
  }

  pending(): number {
    let n = 0;
    for (const w of this.wires.values()) if (w.reset || (w.keep && this.changed(w))) n++;
    for (const b of this.boxes.values()) if (b.reset || this.moved(b)) n++;
    return n;
  }

  // Что вернуть к автотрассе: выделенные линии с ручной трассой и выбранная коробка
  resettable(): { wires: string[]; box: string | null } {
    const wires = [...new Set([...this.sel].map((k) => k.split("#")[0]))]
      .filter((id) => this.wires.get(id)!.manual || this.wires.get(id)!.keep);
    const b = this.box ? this.boxes.get(this.box) : undefined;
    return { wires, box: b && (b.manual || this.moved(b)) ? this.box : null };
  }

  // Вернуть к автотрассе: ручная трасса из файла — убрать (null в POST), новая — откатить
  reset() {
    const { wires, box } = this.resettable();
    for (const id of wires) {
      const w = this.wires.get(id)!;
      if (w.manual) Object.assign(w, { reset: true, keep: false });
      else Object.assign(w, { path: copy(w.orig), keep: false });
    }
    if (box) {
      const b = this.boxes.get(box)!;
      if (b.manual) b.reset = true;
      else b.at = [b.orig[0], b.orig[1]];
    }
  }

  // Под курсором (мм листа): коробка важнее линии; линия — ближайший участок. Линии пучка
  // в модели лежат друг на друге (полосы — только на листе): prefer — линия, чья полоса
  // на листе под курсором
  hit(mx: number, my: number, tol: number, prefer: string | null = null): Hit | null {
    for (const [id, b] of this.boxes) {
      const [cx, cy] = this.toSheet(this.center(b)), half = (b.size * this.k) / 2 + tol;
      if (Math.abs(mx - cx) <= half && Math.abs(my - cy) <= half) return { kind: "box", id };
    }
    let best: { id: string; i: number; d: number; own: boolean } | null = null;
    const hidden = this.hidden();
    for (const [id, w] of this.wires) {
      const st = this.style.get(id);
      if (st && hidden.has(st.l)) continue;
      const pts = w.path.map((p) => this.toSheet(p));
      for (let i = 0; i + 1 < pts.length; i++) {
        const d = segDistance([mx, my], pts[i], pts[i + 1]);
        const own = id === prefer;
        if (d <= tol && (!best || (own && !best.own) || (own === best.own && d < best.d))) {
          best = { id, i, d, own };
        }
      }
    }
    return best && { kind: "seg", id: best.id, i: best.i };
  }

  cursor(hit: Hit | null): string {
    if (!hit) return "";
    if (hit.kind === "box") return "move";
    const w = this.wires.get(hit.id)!;
    return isH(w.path[hit.i], w.path[hit.i + 1]) ? "ns-resize" : "ew-resize";
  }

  private snapshot(): Snapshot {
    return {
      wires: [...this.wires].map(([id, w]) => [id, copy(w.path), w.keep, w.reset]),
      boxes: [...this.boxes].map(([id, b]) => [id, [b.at[0], b.at[1]], b.reset]),
    };
  }

  undo(): boolean {
    const s = this.history.pop();
    if (!s) return false;
    for (const [id, path, keep, reset] of s.wires) Object.assign(this.wires.get(id)!, { path, keep, reset });
    for (const [id, at, reset] of s.boxes) Object.assign(this.boxes.get(id)!, { at, reset });
    this.sel.clear();
    return true;
  }

  clearSelection() { this.sel.clear(); this.hover = null; this.box = null; }

  // Нажатие на участок или коробку; true — можно тянуть. Cmd/Ctrl — добавить участок
  // к выделению или убрать; коробки в выделение не попадают
  press(hit: Hit, additive: boolean, mx: number, my: number): boolean {
    if (hit.kind === "box") {
      this.box = hit.id;
      const b = this.boxes.get(hit.id)!;
      const wires = [...this.wires].filter(([, w]) => w.from === hit.id || w.to === hit.id)
        .map(([id, w]) => ({ id, atStart: w.from === hit.id, path: copy(w.path) }));
      this.drag = { kind: "box", id: hit.id, sx: mx, sy: my, at: [b.at[0], b.at[1]], wires, moved: false };
      return true;
    }
    const key = `${hit.id}#${hit.i}`;
    if (additive) {
      if (this.sel.has(key)) { this.sel.delete(key); return false; }
      this.sel.add(key);
    } else if (!this.sel.has(key)) {
      this.sel = new Set([key]);
    }
    const parts = new Map<string, { path: XY[]; segs: Set<number> }>();
    for (const k of this.sel) {
      const [id, i] = k.split("#");
      if (!parts.has(id)) parts.set(id, { path: copy(this.wires.get(id)!.path), segs: new Set() });
      parts.get(id)!.segs.add(Number(i));
    }
    this.drag = { kind: "seg", sx: mx, sy: my, parts, dx: 0, dy: 0, moved: false };
    return true;
  }

  move(mx: number, my: number) {
    const d = this.drag;
    if (!d) return;
    if (!d.moved) { this.history.push(this.snapshot()); d.moved = true; }
    const dx = snap((mx - d.sx) / this.k), dy = snap(-(my - d.sy) / this.k);
    if (d.kind === "seg") {
      d.dx = dx; d.dy = dy;
      for (const [id, { path, segs }] of d.parts) {
        Object.assign(this.wires.get(id)!, { path: dragPath(path, segs, dx, dy), keep: true, reset: false });
      }
      return;
    }
    const b = this.boxes.get(d.id)!;
    let at: XY = [d.at[0] + dx, d.at[1] + dy];
    if (b.span) {  // коробка на стене ездит вдоль своей стены
      const [s0, s1] = b.span;
      at = isH(s0, s1) ? [clamp(at[0], s0[0], s1[0]), s0[1]] : [s0[0], clamp(at[1], s0[1], s1[1])];
    }
    b.at = at; b.reset = false;
    for (const f of d.wires) this.wires.get(f.id)!.path = moveEnd(f.path, f.atStart, this.node(b));
  }

  // Конец перетаскивания: выделение — на те же участки в новых трассах
  release() {
    const d = this.drag;
    this.drag = null;
    if (!d || !d.moved || d.kind !== "seg") return;
    const sel = new Set<string>();
    for (const [id, { path, segs }] of d.parts) {
      const now = this.wires.get(id)!.path;
      for (const i of segs) {
        const h = isH(path[i], path[i + 1]);
        const mid: XY = [(path[i][0] + path[i + 1][0]) / 2 + (h ? 0 : d.dx),
                         (path[i][1] + path[i + 1][1]) / 2 + (h ? d.dy : 0)];
        const j = now.findIndex((p, n) => n + 1 < now.length && isH(p, now[n + 1]) === h
          && segDistance(mid, p, now[n + 1]) < 0.5);
        if (j >= 0) sel.add(`${id}#${j}`);
      }
    }
    this.sel = sel;
  }

  // Для POST /wiring: ручные трассы — только у линий, которые тянули; линии, что лишь
  // следуют за коробкой, после сборки проложатся заново. null — вернуть автотрассу
  payload() {
    const wires: Record<string, unknown> = {}, boxes: Record<string, unknown> = {};
    const r = (p: XY) => p.map((v) => Math.round(v * 10) / 10);
    for (const [id, w] of this.wires) {
      if (w.reset) wires[id] = null;
      else if (w.keep && this.changed(w)) wires[id] = { from: w.from, to: w.to, path: w.path.map(r) };
    }
    for (const [id, b] of this.boxes) {
      if (b.reset) boxes[id] = null;
      else if (this.moved(b)) boxes[id] = { room: b.room, group: b.group, at: r(b.at) };
    }
    return { wires, boxes };
  }

  // Линии, которые сейчас правятся: с выделенными участками, перетаскиваемые и идущие
  // за переносимой коробкой
  flowing(): Set<string> {
    const out = new Set([...this.sel].map((k) => k.split("#")[0]));
    const d = this.drag;
    if (d && d.kind === "seg") for (const id of d.parts.keys()) out.add(id);
    if (d && d.kind === "box" && d.moved) for (const f of d.wires) out.add(f.id);
    return out;
  }

  // Поверх листа: изменённые линии и коробки, бегущий пунктир правки, выделение и участок
  // под курсором; now — время кадра, мс
  paint(ctx: CanvasRenderingContext2D, pxPerMm: number, now: number, dpr: number) {
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    const minW = MIN_LINE_PX / pxPerMm;
    const px = (n: number) => (n * dpr) / pxPerMm;  // px экрана → мм листа
    const line = (pts: XY[]) => {
      ctx.beginPath();
      pts.forEach((p, n) => { const [x, y] = this.toSheet(p); if (n) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
      ctx.stroke();
    };
    const hidden = this.hidden();
    for (const [id, w] of this.wires) {
      if (!this.changed(w)) continue;
      const st = this.style.get(id);
      if (st && hidden.has(st.l)) continue;
      ctx.strokeStyle = screenColor(st ? st.c : "#000000");
      ctx.lineWidth = Math.max(st?.w ?? 0.25, px(CABLE_MIN_PX), minW);
      line(w.path);
    }
    const ink = screenColor("#000000");
    for (const [id, b] of this.boxes) {
      const lit = this.box === id || (this.hover?.kind === "box" && this.hover.id === id);
      if (!this.moved(b) && !lit) continue;
      const [cx, cy] = this.toSheet(this.center(b)), s = b.size * this.k;
      if (this.moved(b)) {
        ctx.fillStyle = palette.paper; ctx.fillRect(cx - s / 2, cy - s / 2, s, s);
        ctx.strokeStyle = ink; ctx.lineWidth = Math.max(0.25, minW);
        ctx.strokeRect(cx - s / 2, cy - s / 2, s, s);
        ctx.fillStyle = ink; ctx.font = `${s * 0.9}px "IBM Plex Sans", sans-serif`;
        ctx.fillText(b.label, cx + s * 0.7, cy - s * 0.7);
      }
      if (lit) {
        ctx.strokeStyle = palette.hl; ctx.lineWidth = px(2.5);
        ctx.strokeRect(cx - s / 2 - px(1.5), cy - s / 2 - px(1.5), s + px(3), s + px(3));
      }
    }
    // Правящиеся линии — бегущим пунктиром от источника к цели
    const flow = this.flowing();
    if (flow.size) {
      const t = REDUCED_MOTION ? 0 : now / 1000;
      ctx.strokeStyle = palette.hl; ctx.lineWidth = px(FLOW_WIDTH_PX);
      ctx.setLineDash([px(FLOW_DASH_PX), px(FLOW_GAP_PX)]);
      ctx.lineDashOffset = -px(t * FLOW_SPEED_PX);
      for (const id of flow) line(this.wires.get(id)!.path);
      ctx.setLineDash([]); ctx.lineDashOffset = 0;
    }
    const segs = [...this.sel];
    if (this.hover?.kind === "seg") segs.push(`${this.hover.id}#${this.hover.i}`);
    ctx.strokeStyle = palette.hl;
    for (const key of segs) {
      const [id, i] = key.split("#"), w = this.wires.get(id), n = Number(i);
      if (!w || n + 1 >= w.path.length) continue;
      ctx.globalAlpha = this.sel.has(key) ? 0.85 : 0.5;
      ctx.lineWidth = px(6);
      line([w.path[n], w.path[n + 1]]);
    }
    ctx.globalAlpha = 1;
  }
}
