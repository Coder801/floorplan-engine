// Лист .epd в canvas: масштаб, сдвиг, подсказки, выделение линии и правка трасс.
// Рисование — вне React (тысячи примитивов, каждый кадр); с остальным интерфейсом лист
// связан через общее состояние (store.ts): под курсором, выделение, подсказка, слои.

import {
  CABLE_MIN_PX, DIM_ALPHA, EDIT_HIT_PX, EDIT_MOVE_PX, FOCUS_MAX, FOCUS_MS, NEIGHBOR_ALPHA,
  FIT_SHRINK, REDUCED_MOTION, SHEET_ONLY, TIP_GAP, VIEW_PAD,
} from "../consts";
import { WiringEdit, type Hit } from "../edit/WiringEdit";
import { expand, PageIndex } from "../page";
import { palette, refreshPalette, screenColor } from "../palette";
import { view } from "../store";
import type { Page } from "../types";
import { bbox, downloadSheetPng, inBox, inView, paint, viewOf, type DrawItem } from "./paint";

const TIP_WIDTH = 320;  // закреплённая подсказка (max-width в CSS) — место справа при наезде

interface Drag {
  edit?: boolean;
  x: number; y: number;
  ox?: number; oy?: number;
  moved: boolean;
  additive?: boolean;
}

export class SheetView {
  readonly items: DrawItem[];
  readonly ed: WiringEdit | null;
  saved = false;          // правки записаны, лист пересобирается
  onEditChange: () => void = () => {};
  onZoom: (label: string) => void = () => {};
  private ctx: CanvasRenderingContext2D;
  private w = 1; private h = 1; private dpr = 1;
  private scale = 1; private fitScale = 1; private ox = 0; private oy = 0;
  private frame = 0; private flowFrame = 0;
  private drag: Drag | null = null;
  private readonly cleanup: (() => void)[] = [];

  constructor(private readonly canvas: HTMLCanvasElement, private readonly wrap: HTMLElement,
              readonly page: Page, readonly index: PageIndex) {
    this.items = page.items.filter((i) => !SHEET_ONLY.has(i.l))
      .map((i) => ({ ...i, box: bbox(i.d) }))
      .filter((i) => inView(page, i.box))
      .map((i) => ({ ...i, path: new Path2D(i.d) }));
    this.ed = page.edit && page.model ? new WiringEdit(page, this.items, () => view.get().hidden) : null;
    this.ctx = canvas.getContext("2d")!;
    const resize = new ResizeObserver(() => { this.layout(); this.fit(); });
    resize.observe(wrap);
    this.cleanup.push(() => resize.disconnect());
    // Перерисовка — только когда меняется то, что видно на листе (подсказка у курсора — нет)
    let seen: unknown[] = [];
    this.cleanup.push(view.subscribe(() => {
      const s = view.get();
      const now = [s.hover, s.lit, s.selected, s.neighbors, s.hidden, s.editMode, s.show3d, s.themeTick];
      if (now.some((v, i) => v !== seen[i])) { seen = now; this.draw(); }
    }));
    this.bind();
  }

  destroy() {
    for (const f of this.cleanup) f();
    cancelAnimationFrame(this.frame); cancelAnimationFrame(this.flowFrame);
  }

  editing() {
    const s = view.get();
    return s.editMode && !!this.ed && !this.saved && !s.show3d;
  }

  private layout() {
    const r = this.wrap.getBoundingClientRect();
    this.w = r.width; this.h = r.height;
    this.dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(r.width * this.dpr);
    this.canvas.height = Math.round(r.height * this.dpr);
  }

  fit() {
    const [x0, y0, x1, y1] = viewOf(this.page);
    this.scale = FIT_SHRINK * Math.min((this.w - 2 * VIEW_PAD) / (x1 - x0), (this.h - 2 * VIEW_PAD) / (y1 - y0));
    this.fitScale = this.scale;
    this.ox = (this.w - (x1 + x0) * this.scale) / 2;
    this.oy = (this.h - (y1 + y0) * this.scale) / 2;
    this.draw();
  }

  zoomBy(f: number, x = this.w / 2, y = this.h / 2) {
    const mx = (x - this.ox) / this.scale, my = (y - this.oy) / this.scale;
    this.scale = Math.min(Math.max(this.scale * f, this.fitScale * 0.5), this.fitScale * 40);
    this.ox = x - mx * this.scale; this.oy = y - my * this.scale;
    this.draw();
  }

  private isLit(o: string | undefined): boolean {
    if (!o) return false;
    const { hover, lit } = view.get();
    if (o === hover) return true;
    return !!lit && expand(o).some((k) => lit.has(k));
  }

  // Как рисовать примитив: цвет, прозрачность, во сколько толще
  private look(it: DrawItem): [string, number, number] {
    const o = it.o;
    if (this.isLit(o)) return [palette.hl, 1, 2];
    const c = screenColor(it.c);
    const { selected, neighbors } = view.get();
    if (!selected || !this.index.interactive(o)) return [c, 1, 1];
    if (selected.has(o)) return [c, 1, 1.8];
    return neighbors && neighbors.has(o) ? [c, NEIGHBOR_ALPHA, 1] : [c, DIM_ALPHA, 1];
  }

  // Выделить линию и закрепить подсказку; focus — ещё и навести на неё вид (двойной клик)
  select(o: string | null, focus = false) {
    if (!o) { this.clearSelection(); return; }
    const chain = this.index.chainOf(o);
    view.set({ selected: chain, neighbors: this.index.neighborsOf(chain), pinned: o, tip: null });
    if (focus) this.showKeys(chain);
  }

  clearSelection() {
    view.set({ selected: null, neighbors: null, pinned: null });
  }

  // Вписать объекты в свободную часть экрана (левее подсказки), плавно; сильнее
  // FOCUS_MAX от «весь чертёж» не увеличивать
  private showKeys(keys: Set<string>) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const it of this.items) {
      if (!it.o || !keys.has(it.o)) continue;
      x0 = Math.min(x0, it.box[0]); y0 = Math.min(y0, it.box[1]);
      x1 = Math.max(x1, it.box[2]); y1 = Math.max(y1, it.box[3]);
    }
    if (!isFinite(x0)) return;
    const right = TIP_WIDTH + 2 * TIP_GAP;  // занято подсказкой справа
    const aw = Math.max(this.w - right - 2 * VIEW_PAD, 80), ah = Math.max(this.h - 2 * VIEW_PAD, 80);
    const bw = Math.max(x1 - x0, 1), bh = Math.max(y1 - y0, 1);
    const scale = Math.min(aw / bw, ah / bh, this.fitScale * FOCUS_MAX);
    this.animate(scale, VIEW_PAD + (aw - bw * scale) / 2 - x0 * scale, VIEW_PAD + (ah - bh * scale) / 2 - y0 * scale);
  }

  private animate(scale: number, ox: number, oy: number) {
    const from = { scale: this.scale, ox: this.ox, oy: this.oy }, t0 = performance.now();
    const step = (now: number) => {
      const t = Math.min((now - t0) / FOCUS_MS, 1), e = 1 - (1 - t) ** 3;
      this.scale = from.scale * (scale / from.scale) ** e;  // масштаб — по логарифму
      this.ox = from.ox + (ox - from.ox) * e;
      this.oy = from.oy + (oy - from.oy) * e;
      this.draw();
      if (t < 1) this.frame = requestAnimationFrame(step);
    };
    cancelAnimationFrame(this.frame);
    this.frame = requestAnimationFrame(step);
  }

  draw() {
    if (view.get().show3d) return;  // лист закрыт 3D
    const { ctx } = this;
    refreshPalette();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = palette.paper;  // фон блока и чертежа — один
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    const k = this.dpr * this.scale;
    ctx.setTransform(k, 0, 0, k, this.dpr * this.ox, this.dpr * this.oy);
    const [x0, y0, x1, y1] = viewOf(this.page);
    ctx.save();
    ctx.beginPath(); ctx.rect(x0, y0, x1 - x0, y1 - y0); ctx.clip();
    // Изменённые линии и коробки рисуются по правке, а не примитивами листа
    const skip = this.ed ? this.ed.hiddenKeys() : null;
    const items = skip && skip.size ? this.items.filter((it) => !it.o || !skip.has(it.o)) : this.items;
    const hidden = view.get().hidden;
    paint(ctx, items, k, (it) => this.look(it), hidden, CABLE_MIN_PX * this.dpr);
    if (this.ed) this.ed.paint(ctx, k, performance.now(), this.dpr);
    ctx.restore();
    // Бегущий пунктир — следующий кадр, пока есть правящиеся линии
    if (this.editing() && !REDUCED_MOTION && !this.flowFrame && this.ed!.flowing().size) {
      this.flowFrame = requestAnimationFrame(() => { this.flowFrame = 0; this.draw(); });
    }
    this.onZoom(`${Math.round((this.scale / this.fitScale) * 100)}%`);
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
      this.zoomBy(Math.exp(-ev.deltaY * 0.0015), x, y);
    }, { passive: false });
    this.on("pointerdown", (ev) => {
      // Режим правки: участок линии или коробка — тянуть их, мимо — сдвиг чертежа
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
    // Клик без сдвига — выделить линию и закрепить подсказку; мимо — снять выделение
    this.on("pointerup", (ev) => {
      const drag = this.drag;
      if (drag?.edit) { this.stop(); this.editChanged(); return; }
      const click = drag && !drag.moved, additive = drag?.additive;
      this.stop();
      if (!click) return;
      if (this.editing() && !additive) { this.ed!.sel.clear(); this.ed!.box = null; this.onEditChange(); }
      this.select(this.objectAt(ev));
    });
    // Закреплённая подсказка — до потери фокуса; Esc снимает и выделение
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
    this.on("pointercancel", () => this.stop());
    this.on("pointerleave", () => this.setHover(null));
    // Двойной клик по объекту — навести на его линию; мимо — весь чертёж
    this.on("dblclick", (ev) => {
      const o = this.objectAt(ev);
      if (o) this.select(o, true);
      else this.fit();
    });
  }

  private stop() {
    if (this.drag?.edit) this.ed!.release();
    this.drag = null;
    this.canvas.classList.remove("drag");
  }

  private editChanged() { this.onEditChange(); this.draw(); }

  undo() { if (this.ed?.undo()) this.editChanged(); }

  // Режим «Править трассы» выключен — выделение участков и подсветка правки снимаются
  editModeChanged() {
    if (!view.get().editMode && this.ed) this.ed.clearSelection();
    this.canvas.style.cursor = "";
    this.editChanged();
  }

  // Объект под курсором: кандидаты по габаритам, затем точная проверка пути; меньший — главнее
  private objectAt(ev: MouseEvent): string | null {
    const { x, y, mx, my } = this.toSheet(ev);
    const tol = 4 / this.scale;
    const { ctx } = this;
    const k = this.dpr * this.scale;
    const hidden = view.get().hidden;
    ctx.setTransform(k, 0, 0, k, this.dpr * this.ox, this.dpr * this.oy);
    let best: { o: string; area: number } | null = null;
    for (const it of this.items) {
      if (hidden.has(it.l) || !this.index.interactive(it.o) || !inBox(it.box, mx, my, tol)) continue;
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
    if (!o || view.get().pinned) return;  // закреплённая подсказка стоит на месте
    const { x, y } = this.toSheet(ev);
    view.set({ tip: { key: o, x, y } });
  }

  private setHover(o: string | null) {
    const s = view.get();
    if (o === s.hover && (o || !s.tip)) return;
    view.set({ hover: o, ...(o ? {} : { tip: null }) });
  }

  // PNG для альбома: весь лист с таблицами и штампом, цвета листа, не больше A3 при 150 dpi
  downloadPng(filename: string) {
    downloadSheetPng(this.page, filename);
  }
}
