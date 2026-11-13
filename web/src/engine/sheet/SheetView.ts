// Drawing in canvas: zoom, pan, hints, line selection and route editing.
// Drawing happens outside React (thousands of primitives, every frame); the sheet talks to the
// rest of the interface through shared state (store.ts): hover, selection, hint, layers.
// Sheets with a plan share one drawing (sheet/drawing.ts): switching the tab calls setPage
// without a new canvas, giving the other sheet's layers, hints and editing at the same zoom and pan.

import { WiringEdit, type Hit } from "@/engine/edit/WiringEdit";
import {
  CABLE_MIN_PX, DIM_ALPHA, EDIT_HIT_PX, EDIT_MOVE_PX, FOCUS_MS, NEIGHBOR_ALPHA,
  FIT_SHRINK, REDUCED_MOTION, SCREEN_BOLD, STACK_MS, SYMBOL_GROW, TIP_GAP, VIEW_PAD,
} from "@/shared/consts";
import { expand, filteredKeys, PageIndex } from "@/shared/page";
import { palette, refreshPalette, screenColor } from "@/shared/palette";
import { view } from "@/shared/store";
import type { Page } from "@/shared/types";
import { clampStep, Glide, LAST_STEP, PinchSteps, RAIL_PX, stepBelow, WheelSteps, ZOOM_STEPS, zoomLabel, type Zoom } from "@/shared/zoom";
import { layerShown, objectLayers, sceneOf, type Drawing, type DrawingItem } from "./drawing";
import { followsObject, linkEnds, objectVisible, ownLayers, repeatsNumbers, scoped, wiringChains } from "./views";
import { FLOOR_ALPHA, FLOOR_FADE_MS, floorPath, stepFades } from "./floors";
import { gridStep, paintGrid, paperRings } from "./grid";
import { inBox, paint, type DrawItem } from "./paint";
import { Pinch } from "./pinch";
import { grownBox, isSymbol, openStacks, pointStacks, symbolCenters, type Stack } from "./stacks";

const TIP_WIDTH = 320;  // pinned hint (max-width in CSS): room on the right when they overlap

// Primitive path on the drawing: from another sheet, shifted onto sheet base
function pathOf(it: DrawingItem): Path2D {
  const p = new Path2D(it.d), { f, dx, dy } = it.shift;
  if (f === 1 && !dx && !dy) return p;
  const out = new Path2D();
  out.addPath(p, new DOMMatrix([f, 0, 0, f, dx, dy]));
  return out;
}

// A path moved by (dx, dy) and grown f times about (cx, cy)
function movedPath(p: Path2D, f: number, cx: number, cy: number, dx = 0, dy = 0): Path2D {
  const out = new Path2D();
  out.addPath(p, new DOMMatrix([f, 0, 0, f, cx * (1 - f) + dx, cy * (1 - f) + dy]));
  return out;
}

const easeOut = (t: number) => 1 - (1 - t) ** 3;

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
  // Floor highlight under the cursor: share shown per floor, its frame and the last step time
  private fades = new Map<string, number>(); private fadeFrame = 0; private fadeAt = 0;
  private drag: Drag | null = null;
  private readonly pinch = new Pinch();
  private readonly layerOf: Map<string, string>;
  private readonly lines: Record<string, string[]>;
  private fitted = true;  // the view is "whole drawing": refit on resize, otherwise keep it
  private readonly cleanup: (() => void)[] = [];
  // Socket stacks (stacks.ts): all of the drawing, those of this view, a hidden socket → its
  // stack, the open share of each stack, its frame and the last step time, the one the pointer holds
  private readonly allStacks: Stack[];
  private stacks: Stack[] = [];
  private stackOf = new Map<string, Stack>();
  private opens = new Map<string, number>(); private openFrame = 0; private openAt = 0;
  private held: string | null = null;
  private readonly paper: Path2D;  // the flat: plain paper, no grid (grid.ts)

  constructor(private readonly canvas: HTMLCanvasElement, private readonly wrap: HTMLElement,
              readonly drawing: Drawing, page: Page, index: PageIndex) {
    // Point and box symbols are larger on screen, each about its own centre
    const raw = drawing.items.map((i) => ({ ...i, w: i.w && i.w * i.shift.f, path: pathOf(i) }));
    const centers = symbolCenters(raw);
    this.items = raw.map((it) => {
      const c = isSymbol(it) ? centers.get(it.o!) : undefined;
      return c ? { ...it, path: movedPath(it.path, SYMBOL_GROW, c[0], c[1]), box: grownBox(it.box, c, SYMBOL_GROW) } : it;
    });
    this.allStacks = pointStacks(this.items);
    this.has3d = !!sceneOf(drawing);
    this.paper = floorPath(paperRings(drawing));
    this.layerOf = objectLayers(drawing);
    this.lines = wiringChains(drawing);
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
      const now = [s.hover, s.lit, s.selected, s.neighbors, s.hidden, s.extra, s.editMode, s.show3d, s.themeTick, s.filter3d, s.electricalView, s.systemsOff, s.cables];
      if (now.some((v, i) => v !== seen[i])) { seen = now; this.applyView(); this.draw(); }
    }));
    this.bind();
  }

  // Another tab of the same drawing: its layers, hints and editing; zoom and pan stay the same.
  // Unsaved route edits are lost, so Viewer asks before switching
  setPage(page: Page, index: PageIndex, redraw = true) {
    this.page = page;
    this.index = index;
    this.applyView();
    const model = this.drawing.base.model;
    this.ed = page.edit && model ? new WiringEdit(page, this.items, this.shown, model) : null;
    this.saved = false;
    if (redraw) this.draw();
  }

  // Layers of this tab in the chosen view (views.ts)
  private applyView() {
    const st = view.get();
    this.own = ownLayers(this.drawing, this.page, st.electricalView, st.cables, st.systemsOff) ?? new Set(this.items.map((i) => i.l));
    // Sockets and switches close into stacks on the electrical views; the wiring and lighting
    // sheets keep every symbol, a line runs to each
    this.stacks = this.page.stage === "electrical" ? this.allStacks.filter((s) => this.shown(s.layer)) : [];
    this.stackOf = new Map(this.stacks.flatMap((s) => s.rest.map((k) => [k, s] as const)));
    if (this.held && !this.stacks.some((s) => s.label === this.held)) this.held = null;
  }

  // Stacks open: towards the wanted ones, smoothly; while one moves, the next frame is requested
  private stepStacks() {
    const s = view.get(), now = performance.now();
    const want = openStacks(this.stacks, this.held, [s.hover, s.pinned, s.selected, s.lit]);
    const dt = this.openAt ? now - this.openAt : 0;
    const moving = stepFades(this.opens, want, dt, REDUCED_MOTION ? 0 : STACK_MS);
    this.openAt = moving ? now : 0;
    if (moving && !this.openFrame) {
      this.openFrame = requestAnimationFrame(() => { this.openFrame = 0; this.draw(); });
    }
  }

  // Closed stacks: a count on the socket at the wall, fading as the stack opens
  private paintCounts(ctx: CanvasRenderingContext2D) {
    const r = 7 / this.scale;
    ctx.save();
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.font = `600 ${10 / this.scale}px system-ui, sans-serif`;
    const off = this.filtered();
    for (const st of this.stacks) {
      const share = this.opens.get(st.key) ?? 0;
      if (share >= 1 || off.has(st.anchor)) continue;
      const [x, y] = st.count;
      ctx.globalAlpha = 1 - share;
      ctx.fillStyle = palette.pin;
      ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI); ctx.fill();
      ctx.fillStyle = palette.paper;
      ctx.fillText(String(st.rest.length + 1), x, y + 0.5 / this.scale);
    }
    ctx.restore();
  }

  // A label or a box on the electrics views: only with its object
  private readonly inView = (it: { o?: string; l: string }) => !repeatsNumbers(this.page, it)
    && (!scoped(this.page) || !it.o || !followsObject(it.l) || objectVisible(it.o, this.shown, this.layerOf, this.lines));

  // Objects of the groups switched off in the side panel
  private filtered() {
    return filteredKeys(this.page.groups, view.get().filter3d.groups);
  }

  // A layer is visible on this tab: its own until switched off, one from another sheet if switched on
  readonly shown = (l: string) => {
    const { hidden, extra } = view.get();
    return layerShown(this.own, hidden, extra, l);
  };

  destroy() {
    for (const f of this.cleanup) f();
    cancelAnimationFrame(this.frame); cancelAnimationFrame(this.flowFrame); cancelAnimationFrame(this.fadeFrame);
    cancelAnimationFrame(this.openFrame);
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
    if (!lit) return false;
    // A question about a room (room:hall) also lights the zones of it on the plan
    const room = o.startsWith("zone:") ? `room:${o.slice(5, o.lastIndexOf("."))}` : null;
    return (linkEnds(o) ?? expand(o)).some((k) => lit.has(k)) || (!!room && lit.has(room));
  }

  // Floors filled now: the room or zone under the cursor and the lit ones (table row, question)
  private litFloors(): Set<string> {
    return new Set(Object.keys(this.index.floors).filter((k) => this.isLit(k)));
  }

  // Floor fills under the drawing; while one is fading, the next frame is requested
  private paintFloors(ctx: CanvasRenderingContext2D) {
    const now = performance.now();
    const dt = this.fadeAt ? now - this.fadeAt : 0;
    const moving = stepFades(this.fades, this.litFloors(), dt, REDUCED_MOTION ? 0 : FLOOR_FADE_MS);
    this.fadeAt = moving ? now : 0;
    ctx.save();
    ctx.fillStyle = palette.hl;
    for (const [key, share] of this.fades) {
      const rings = this.index.floors[key];
      if (!rings) continue;
      ctx.globalAlpha = FLOOR_ALPHA * share;
      ctx.fill(floorPath(rings), "evenodd");
    }
    ctx.restore();
    if (moving && !this.fadeFrame) {
      this.fadeFrame = requestAnimationFrame(() => { this.fadeFrame = 0; this.draw(); });
    }
  }

  // How to draw a primitive: colour, opacity, how much thicker; a socket of a stack slides out
  // from the socket at the wall and shows as the stack opens
  private look(it: DrawItem): [string, number, number, Path2D?] {
    const st = it.o ? this.stackOf.get(it.o) : undefined;
    if (!st) return this.lookOf(it);
    const share = this.opens.get(st.key) ?? 0;
    if (!share) return ["", 0, 1];
    const [c, alpha, k] = this.lookOf(it);
    if (share >= 1) return [c, alpha, k];
    const [dx, dy] = st.shift[it.o!], back = 1 - easeOut(share);
    return [c, alpha * share, k, movedPath(it.path, 1, 0, 0, dx * back, dy * back)];
  }

  private lookOf(it: DrawItem): [string, number, number] {
    const o = it.o;
    // A floor under the cursor is shown by its fill: its outline (along the walls) and label stay
    const floorHover = !!o && o === view.get().hover && o in this.index.floors;
    if (!floorHover && this.isLit(o)) return [palette.hl, 1, 2];
    const c = screenColor(it.c);
    const { selected, neighbors } = view.get();
    if (!selected) return [c, 1, 1];
    // A light link is in its switch bundle (chains of the lighting sheet); a build without
    // them lights it by its points. The rest are dimmed with the drawing
    const ends = linkEnds(o);
    if (ends) return selected.has(o!) || ends.some((e) => selected.has(e)) ? [c, 1, 1.8] : [c, DIM_ALPHA, 1];
    if (!this.index.interactive(o)) return [c, 1, 1];
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

  // Faint squares over the whole block, a round number of model mm each (grid.ts); a sheet
  // without a plan counts in sheet mm
  private paintGrid(ctx: CanvasRenderingContext2D) {
    const [m, tx, ty] = this.drawing.base.model ?? [1, 0, 0];
    const k = this.dpr * this.scale;
    paintGrid(ctx, this.dpr * this.ox + tx * k, this.dpr * this.oy + ty * k, gridStep(k * m) * m * k);
  }

  draw() {
    if (view.get().show3d && this.has3d) return;  // the drawing is covered by 3D
    const { ctx } = this;
    refreshPalette();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = palette.paper;  // the block and drawing background are the same
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    this.paintGrid(ctx);
    const k = this.dpr * this.scale;
    ctx.setTransform(k, 0, 0, k, this.dpr * this.ox, this.dpr * this.oy);
    ctx.fillStyle = palette.paper;  // the flat itself stays plain
    ctx.fill(this.paper);
    const [x0, y0, x1, y1] = this.drawing.view;
    ctx.save();
    ctx.beginPath(); ctx.rect(x0, y0, x1 - x0, y1 - y0); ctx.clip();
    // Changed lines and boxes are drawn from the edit, not from sheet primitives; while editing
    // the whole wiring is shown, so the group filter is off
    const skip = this.ed && this.editing() ? this.ed.hiddenKeys() : this.filtered();
    const items = this.items.filter((it) => this.inView(it) && (!it.o || !skip.has(it.o)));
    this.paintFloors(ctx);
    this.stepStacks();
    paint(ctx, items, k, (it) => this.look(it), this.shown, CABLE_MIN_PX * this.dpr, SCREEN_BOLD);
    this.paintCounts(ctx);
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
    this.on("pointerleave", () => { this.hold(null, null); this.setHover(null); });
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
    const off = this.editing() ? null : this.filtered();
    for (const it of this.items) {
      if (it.o && off?.has(it.o)) continue;
      if (it.o && this.stackOf.has(it.o) && (this.opens.get(this.stackOf.get(it.o)!.key) ?? 0) < 0.5) continue;
      if (!this.shown(it.l) || !this.inView(it) || !this.index.interactive(it.o) || !inBox(it.box, mx, my, tol)) continue;
      const area = (it.box[2] - it.box[0] + tol) * (it.box[3] - it.box[1] + tol);
      if (best && area >= best.area) continue;
      ctx.lineWidth = 2 * tol;
      const px = x * this.dpr, py = y * this.dpr;
      const hit = area < 25 || (it.k === "f"
        ? ctx.isPointInPath(it.path, px, py) || ctx.isPointInStroke(it.path, px, py)
        : ctx.isPointInStroke(it.path, px, py));
      if (hit) best = { o: it.o!, area };
    }
    if (best) return best.o;
    const area = this.shown("A-WALL") ? this.index.areaAt(mx, my) : null;
    if (this.index.interactive(area)) return area;
    // Nothing drawn under the cursor: the floor of the room or zone (plan sheet)
    const floor = this.index.floorAt(mx, my);
    return this.index.interactive(floor) ? floor : null;
  }

  private pick(ev: MouseEvent) {
    const o = this.objectAt(ev);
    this.hold(o, ev);
    this.setHover(o);
    if (!o || view.get().pinned) return;  // a pinned hint stays in place
    const { x, y } = this.toSheet(ev);
    view.set({ tip: { key: o, x, y } });
  }

  // The pointer keeps a place open (its label: sockets and switches together) while it is on
  // its symbols or in the gaps between them
  private hold(o: string | null, ev: MouseEvent | null) {
    let held: string | null = null;
    if (o) held = this.stacks.find((s) => s.label === o || s.anchor === o || s.rest.includes(o))?.label ?? null;
    if (!held && this.held && ev) {
      const { mx, my } = this.toSheet(ev);
      if (this.stacks.some((s) => s.label === this.held && inBox(s.box, mx, my, 4 / this.scale))) held = this.held;
    }
    if (held !== this.held) { this.held = held; this.draw(); }
  }

  private setHover(o: string | null) {
    const s = view.get();
    if (o === s.hover && (o || !s.tip)) return;
    view.set({ hover: o, ...(o ? {} : { tip: null }) });
  }

}
