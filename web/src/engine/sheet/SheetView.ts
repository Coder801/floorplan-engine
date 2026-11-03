// Drawing in canvas: zoom, pan, hints, line selection and route editing.
// Drawing happens outside React (thousands of primitives, every frame); the sheet talks to the
// rest of the interface through shared state (store.ts): hover, selection, hint, layers.
// Sheets with a plan share one drawing (sheet/drawing.ts): switching the tab calls setPage
// without a new canvas, giving the other sheet's layers, hints and editing at the same zoom and pan.

import { WiringEdit, type Hit } from "@/engine/edit/WiringEdit";
import {
  CABLE_MIN_PX, DIM_ALPHA, EDIT_HIT_PX, EDIT_MOVE_PX, FOCUS_MS, NEIGHBOR_ALPHA,
  FIT_SHRINK, REDUCED_MOTION, TIP_GAP, VIEW_PAD,
} from "@/shared/consts";
import { expand, PageIndex } from "@/shared/page";
import { palette, refreshPalette, screenColor } from "@/shared/palette";
import { view } from "@/shared/store";
import type { Page } from "@/shared/types";
import { clampStep, Glide, LAST_STEP, PinchSteps, RAIL_PX, stepBelow, WheelSteps, ZOOM_STEPS, zoomLabel, type Zoom } from "@/shared/zoom";
import { layerShown, sceneOf, type Drawing, type DrawingItem } from "./drawing";
import { inBox, paint, type DrawItem } from "./paint";
import { Pinch } from "./pinch";

const TIP_WIDTH = 320;  // pinned hint (max-width in CSS): room on the right when they overlap

// Primitive path on the drawing: from another sheet, shifted onto sheet base
function pathOf(it: DrawingItem): Path2D {
  const p = new Path2D(it.d), { f, dx, dy } = it.shift;
  if (f === 1 && !dx && !dy) return p;
  const out = new Path2D();
  out.addPath(p, new DOMMatrix([f, 0, 0, f, dx, dy]));
  return out;
}

interface Drag {
  edit?: boolean;
  x: number; y: number;
  ox?: number; oy?: number;
  moved: boolean;
  additive?: boolean;
}

export class SheetView {
  readonly items: DrawItem[];
  readonly has3d: boolean;  // the drawing has 3D (the wiring sheet scene), on any tab
  ed: WiringEdit | null = null;
  page!: Page;
  index!: PageIndex;
  private own = new Set<string>();
  saved = false;          // edits saved, the sheet is being rebuilt
  onEditChange: () => void = () => {};
  onZoom: (zoom: Zoom) => void = () => {};
  private step = 0;  // zoom step (zoom.ts)
  private readonly wheel = new WheelSteps();
  private readonly pinchSteps = new PinchSteps();
  private readonly glide = new Glide();
  private ctx: CanvasRenderingContext2D;
  private w = 1; private h = 1; private dpr = 1;
  private scale = 1; private fitScale = 1; private ox = 0; private oy = 0;
  private frame = 0; private flowFrame = 0;
  private drag: Drag | null = null;
  private readonly pinch = new Pinch();
  private fitted = true;  // the view is "whole drawing": refit on resize, otherwise keep it
  private readonly cleanup: (() => void)[] = [];

  constructor(private readonly canvas: HTMLCanvasElement, private readonly wrap: HTMLElement,
              readonly drawing: Drawing, page: Page, index: PageIndex) {
    this.items = drawing.items.map((i) => ({ ...i, w: i.w && i.w * i.shift.f, path: pathOf(i) }));
    this.has3d = !!sceneOf(drawing);
    this.setPage(page, index, false);
    this.ctx = canvas.getContext("2d")!;
    // New size (window, phone rotation, bottom panel): a fitted drawing is fitted again, a
    // zoomed one stays as it is
    const resize = new ResizeObserver(() => { this.layout(); if (this.fitted) this.fit(); else this.draw(); });
    resize.observe(wrap);
    this.cleanup.push(() => resize.disconnect());
    // Redraw only when something visible on the sheet changes (the hint at the cursor does not count)
    let seen: unknown[] = [];
    this.cleanup.push(view.subscribe(() => {
      const s = view.get();
      const now = [s.hover, s.lit, s.selected, s.neighbors, s.hidden, s.extra, s.editMode, s.show3d, s.themeTick];
      if (now.some((v, i) => v !== seen[i])) { seen = now; this.draw(); }
    }));
    this.bind();
  }

  // Another tab of the same drawing: its layers, hints and editing; zoom and pan stay the same.
  // Unsaved route edits are lost, so Viewer asks before switching
  setPage(page: Page, index: PageIndex, redraw = true) {
    this.page = page;
    this.index = index;
    this.own = this.drawing.own.get(page) ?? new Set(this.items.map((i) => i.l));
    const model = this.drawing.base.model;
    this.ed = page.edit && model ? new WiringEdit(page, this.items, this.shown, model) : null;
    this.saved = false;
    if (redraw) this.draw();
  }

  // A layer is visible on this tab: its own until switched off, one from another sheet if switched on
  readonly shown = (l: string) => {
    const { hidden, extra } = view.get();
    return layerShown(this.own, hidden, extra, l);
  };

  destroy() {
    for (const f of this.cleanup) f();
    cancelAnimationFrame(this.frame); cancelAnimationFrame(this.flowFrame);
  }

  editing() {
    const s = view.get();
    return s.editMode && !!this.ed && !this.saved && !(s.show3d && this.has3d);
  }

  private layout() {
    const r = this.wrap.getBoundingClientRect();
    this.w = r.width; this.h = r.height;
    this.dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(r.width * this.dpr);
    this.canvas.height = Math.round(r.height * this.dpr);
  }

  fit() {
    this.glide.stop();
    const [x0, y0, x1, y1] = this.drawing.view;
    this.scale = FIT_SHRINK * Math.min((this.w - RAIL_PX - 2 * VIEW_PAD) / (x1 - x0), (this.h - 2 * VIEW_PAD) / (y1 - y0));
    this.fitScale = this.scale;
    this.step = 0;
    this.ox = (this.w - RAIL_PX - (x1 + x0) * this.scale) / 2;
    this.oy = (this.h - (y1 + y0) * this.scale) / 2;
    this.fitted = true;
    this.draw();
  }

  // Neighbouring zoom step at screen point (x, y); none past the ends
  zoomStep(dir: number, x = (this.w - RAIL_PX) / 2, y = this.h / 2) { this.zoomTo(this.step + dir, x, y); }

  // Double click: one step in towards screen point (x, y); if there is no step left, fit the whole drawing
  zoomIn({ x, y }: { x: number; y: number }) {
    if (this.step >= LAST_STEP) this.fit(); else this.zoomStep(1, x, y);
  }

  // Zoom step, smoothly, keeping screen point (x, y) in place
  zoomTo(step: number, x = (this.w - RAIL_PX) / 2, y = this.h / 2) {
    step = clampStep(step);
    if (step === this.step) return;
    cancelAnimationFrame(this.frame);
    this.step = step;
    this.glide.run({ scale: this.scale, ox: this.ox, oy: this.oy }, this.fitScale * ZOOM_STEPS[step], x, y, (v) => { Object.assign(this, v); this.draw(); });
    this.fitted = false;
    this.draw();
  }

  private isLit(o: string | undefined): boolean {
    if (!o) return false;
    const { hover, lit } = view.get();
    if (o === hover) return true;
    return !!lit && expand(o).some((k) => lit.has(k));
  }

  // How to draw a primitive: colour, opacity, how much thicker
  private look(it: DrawItem): [string, number, number] {
    const o = it.o;
    if (this.isLit(o)) return [palette.hl, 1, 2];
    const c = screenColor(it.c);
    const { selected, neighbors } = view.get();
    if (!selected || !this.index.interactive(o)) return [c, 1, 1];
    if (selected.has(o)) return [c, 1, 1.8];
    return neighbors && neighbors.has(o) ? [c, NEIGHBOR_ALPHA, 1] : [c, DIM_ALPHA, 1];
  }

  // Select a line and pin the hint; focus also brings the view to it (double click)
  select(o: string | null, focus = false) {
    if (!o) { this.clearSelection(); return; }
    const chain = this.index.chainOf(o);
    view.set({ selected: chain, neighbors: this.index.neighborsOf(chain), pinned: o, tip: null });
    if (focus) this.showKeys(chain);
  }

  // Open the sheet right on an object (coming from an elevation): fit, select the line and focus on it
  reveal(o: string, around = 0) {
    this.layout(); this.fit();
    if (!this.index.interactive(o)) return;
    this.select(o);
    this.showKeys(this.index.chainOf(o), around);
  }

  clearSelection() {
    view.set({ selected: null, neighbors: null, pinned: null });
  }

  // Fit objects into the free part of the screen (left of the hint), smoothly; never zoom in
  // past the last zoom step (zoom.ts). around: the share of the drawing to keep in view, so a
  // single point is seen in its room
  private showKeys(keys: Set<string>, around = 0) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const it of this.items) {
      if (!it.o || !keys.has(it.o)) continue;
      x0 = Math.min(x0, it.box[0]); y0 = Math.min(y0, it.box[1]);
      x1 = Math.max(x1, it.box[2]); y1 = Math.max(y1, it.box[3]);
    }
    if (!isFinite(x0)) return;
    const right = TIP_WIDTH + 2 * TIP_GAP;  // taken by the hint on the right
    const aw = Math.max(this.w - right - 2 * VIEW_PAD, 80), ah = Math.max(this.h - 2 * VIEW_PAD, 80);
    const [vx0, vy0, vx1, vy1] = this.drawing.view;
    const grow = Math.max(0, Math.max(around * (vx1 - vx0) - (x1 - x0), around * (vy1 - vy0) - (y1 - y0)) / 2);
    x0 -= grow; y0 -= grow; x1 += grow; y1 += grow;
    const bw = Math.max(x1 - x0, 1), bh = Math.max(y1 - y0, 1);
    // The largest zoom step at which the objects are fully visible
    this.step = stepBelow(Math.min(aw / bw, ah / bh) / this.fitScale);
    const scale = this.fitScale * ZOOM_STEPS[this.step];
    this.animate(scale, VIEW_PAD + (aw - bw * scale) / 2 - x0 * scale, VIEW_PAD + (ah - bh * scale) / 2 - y0 * scale);
  }

  private animate(scale: number, ox: number, oy: number) {
    this.glide.stop();
    const from = { scale: this.scale, ox: this.ox, oy: this.oy }, t0 = performance.now();
    this.fitted = false;
    const step = (now: number) => {
      const t = Math.min((now - t0) / FOCUS_MS, 1), e = 1 - (1 - t) ** 3;
      this.scale = from.scale * (scale / from.scale) ** e;  // zoom on a log scale
      this.ox = from.ox + (ox - from.ox) * e;
      this.oy = from.oy + (oy - from.oy) * e;
      this.draw();
      if (t < 1) this.frame = requestAnimationFrame(step);
    };
    cancelAnimationFrame(this.frame);
    this.frame = requestAnimationFrame(step);
  }

  draw() {
    if (view.get().show3d && this.has3d) return;  // the drawing is covered by 3D
    const { ctx } = this;
    refreshPalette();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = palette.paper;  // the block and drawing background are the same
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    const k = this.dpr * this.scale;
    ctx.setTransform(k, 0, 0, k, this.dpr * this.ox, this.dpr * this.oy);
    const [x0, y0, x1, y1] = this.drawing.view;
    ctx.save();
    ctx.beginPath(); ctx.rect(x0, y0, x1 - x0, y1 - y0); ctx.clip();
    // Changed lines and boxes are drawn from the edit, not from sheet primitives
    const skip = this.ed ? this.ed.hiddenKeys() : null;
    const items = skip && skip.size ? this.items.filter((it) => !it.o || !skip.has(it.o)) : this.items;
    paint(ctx, items, k, (it) => this.look(it), this.shown, CABLE_MIN_PX * this.dpr);
    if (this.ed) this.ed.paint(ctx, k, performance.now(), this.dpr);
    ctx.restore();
    // Running dashes: request the next frame while there are lines being edited
    if (this.editing() && !REDUCED_MOTION && !this.flowFrame && this.ed!.flowing().size) {
      this.flowFrame = requestAnimationFrame(() => { this.flowFrame = 0; this.draw(); });
    }
    // Scale bar in model mm (a sheet without a plan has none)
    const m = this.drawing.base.model?.[0];
    this.onZoom({ step: this.step, label: zoomLabel(this.step), pxPerMm: m ? this.scale * m : null });
  }

  private toSheet(ev: MouseEvent) {
    const r = this.canvas.getBoundingClientRect();
    const x = ev.clientX - r.left, y = ev.clientY - r.top;
    return { x, y, mx: (x - this.ox) / this.scale, my: (y - this.oy) / this.scale };
  }

  private editHit(ev: MouseEvent): Hit | null {
    if (!this.editing()) return null;
    const { mx, my } = this.toSheet(ev);
    const o = this.objectAt(ev);
    return this.ed!.hit(mx, my, EDIT_HIT_PX / this.scale, o && o.startsWith("wire:") ? o.slice(5) : null);
  }

  private on<K extends keyof HTMLElementEventMap>(type: K, fn: (ev: HTMLElementEventMap[K]) => void,
                                                  opts?: AddEventListenerOptions) {
    this.canvas.addEventListener(type, fn, opts);
    this.cleanup.push(() => this.canvas.removeEventListener(type, fn));
  }

  private bind() {
    const c = this.canvas;
    this.on("wheel", (ev) => {
      ev.preventDefault();
      const { x, y } = this.toSheet(ev);
      const dir = this.wheel.push(ev.deltaY, performance.now());
      if (dir) this.zoomStep(dir, x, y);
    }, { passive: false });
    this.on("pointerdown", (ev) => {
      // A second finger means a pinch: dragging with the first finger is cancelled
      if (this.pinch.down(ev)) {
        c.setPointerCapture(ev.pointerId);
        this.stop();
        return;
      }
      // Edit mode: a line piece or a box gets dragged, anything else pans the drawing
      const hit = this.editHit(ev);
      if (hit) {
        const { mx, my } = this.toSheet(ev);
        if (this.ed!.press(hit, ev.metaKey || ev.ctrlKey, mx, my)) {
          this.drag = { edit: true, x: ev.clientX, y: ev.clientY, moved: false };
          c.setPointerCapture(ev.pointerId);
        }
        this.editChanged();
        return;
      }
      this.drag = { x: ev.clientX, y: ev.clientY, ox: this.ox, oy: this.oy, moved: false,
                    additive: ev.metaKey || ev.ctrlKey };
      c.setPointerCapture(ev.pointerId); c.classList.add("drag");
    });
    this.on("pointermove", (ev) => {
      const step = this.pinch.move(ev, c.getBoundingClientRect());
      if (step) {
        this.ox += step.dx; this.oy += step.dy;
        this.fitted = false;
        const dir = this.pinchSteps.push(step.f);
        if (dir) this.zoomStep(dir, step.x, step.y); else this.draw();
        return;
      }
      if (this.pinch.busy) return;
      const drag = this.drag;
      if (drag?.edit) {
        if (!drag.moved && Math.abs(ev.clientX - drag.x) + Math.abs(ev.clientY - drag.y) <= EDIT_MOVE_PX) return;
        drag.moved = true;
        const { mx, my } = this.toSheet(ev);
        this.ed!.move(mx, my);
        this.draw();
        return;
      }
      if (drag) {
        if (Math.abs(ev.clientX - drag.x) + Math.abs(ev.clientY - drag.y) > 4) drag.moved = true;
        if (!drag.moved) return;
        this.ox = drag.ox! + ev.clientX - drag.x; this.oy = drag.oy! + ev.clientY - drag.y;
        this.fitted = false;
        this.draw();
        return;
      }
      if (this.editing()) {
        const hit = this.editHit(ev), was = this.ed!.hover;
        this.ed!.hover = hit;
        c.style.cursor = this.ed!.cursor(hit);
        if (JSON.stringify(hit) !== JSON.stringify(was)) this.draw();
      }
      this.pick(ev);
    });
    // A click without a drag selects a line and pins the hint; elsewhere it clears the selection
    this.on("pointerup", (ev) => {
      this.pinch.up(ev);
      if (this.pinch.used) { this.stop(); return; }  // end of a pinch is not a click
      const drag = this.drag;
      if (drag?.edit) { this.stop(); this.editChanged(); return; }
      const click = drag && !drag.moved, additive = drag?.additive;
      this.stop();
      if (!click) return;
      if (this.editing() && !additive) { this.ed!.sel.clear(); this.ed!.box = null; this.onEditChange(); }
      this.select(this.objectAt(ev));
    });
    // A pinned hint stays until focus is lost; Esc also clears the selection
    this.on("blur", () => { if (view.get().pinned) view.set({ pinned: null }); });
    this.on("keydown", (ev) => {
      if (ev.key === "Escape") {
        if (this.ed) { this.ed.sel.clear(); this.ed.box = null; this.onEditChange(); }
        this.clearSelection();
      }
      if (this.editing() && (ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === "z") {
        ev.preventDefault();
        this.undo();
      }
    });
    this.on("pointercancel", (ev) => { this.pinch.up(ev); this.stop(); });
    this.on("pointerleave", () => this.setHover(null));
    // Double click zooms one step in at the click point; at the last step, the whole drawing
    this.on("dblclick", (ev) => this.zoomIn(this.toSheet(ev)));
  }

  private stop() {
    if (this.drag?.edit) this.ed!.release();
    this.drag = null;
    this.canvas.classList.remove("drag");
  }

  private editChanged() { this.onEditChange(); this.draw(); }

  undo() { if (this.ed?.undo()) this.editChanged(); }

  // "Edit routes" mode is off: piece selection and edit highlighting are cleared
  editModeChanged() {
    if (!view.get().editMode && this.ed) this.ed.clearSelection();
    this.canvas.style.cursor = "";
    this.editChanged();
  }

  // Object under the cursor: candidates by bounding box, then an exact path check; the smaller one wins
  private objectAt(ev: MouseEvent): string | null {
    const { x, y, mx, my } = this.toSheet(ev);
    const tol = 4 / this.scale;
    const { ctx } = this;
    const k = this.dpr * this.scale;
    ctx.setTransform(k, 0, 0, k, this.dpr * this.ox, this.dpr * this.oy);
    let best: { o: string; area: number } | null = null;
    for (const it of this.items) {
      if (!this.shown(it.l) || !this.index.interactive(it.o) || !inBox(it.box, mx, my, tol)) continue;
      const area = (it.box[2] - it.box[0] + tol) * (it.box[3] - it.box[1] + tol);
      if (best && area >= best.area) continue;
      ctx.lineWidth = 2 * tol;
      const px = x * this.dpr, py = y * this.dpr;
      const hit = area < 25 || (it.k === "f"
        ? ctx.isPointInPath(it.path, px, py) || ctx.isPointInStroke(it.path, px, py)
        : ctx.isPointInStroke(it.path, px, py));
      if (hit) best = { o: it.o!, area };
    }
    return best ? best.o : null;
  }

  private pick(ev: MouseEvent) {
    const o = this.objectAt(ev);
    this.setHover(o);
    if (!o || view.get().pinned) return;  // a pinned hint stays in place
    const { x, y } = this.toSheet(ev);
    view.set({ tip: { key: o, x, y } });
  }

  private setHover(o: string | null) {
    const s = view.get();
    if (o === s.hover && (o || !s.tip)) return;
    view.set({ hover: o, ...(o ? {} : { tip: null }) });
  }

}
