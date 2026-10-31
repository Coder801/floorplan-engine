// Развёртка стены в своём canvas: рисуется из данных развёртки (ключ elevations страницы),
// а не из примитивов листа — у неё своё поведение, без слоёв и подсветки общего чертежа.
// Стена в мм (x — от левого угла, вид изнутри; y — от пола), подписи — в px экрана: номера
// точек — плашками цвета группы (как линии проводки), отступы снизу, высоты справа.
// Под курсором — точка, коробка или щит (store.hover), клик закрепляет (store.pinned);
// подсвечено то же, что строка «На стене» в боковой панели (store.lit).
// Изометрия (mode "iso", iso.ts) — стена под 45° и часть соседней в углу: тот же плоский
// рисунок стены (плашки, пунктиры, шкалы с подписями) через матрицу её плоскости — подписи и
// размеры тоже изометрические; сосед — полупрозрачный, без шкал, обрыв — волной.
// Под курсором и закреплённое — поверх остального (плашки и символы рисуются последними).

import { Pinch } from "@/engine/sheet/pinch";
import { FIT_SHRINK } from "@/shared/consts";
import { palette, refreshPalette, screenColor } from "@/shared/palette";
import { view } from "@/shared/store";
import type { ElevWall, Elevation, XY } from "@/shared/types";
import { clampStep, Glide, PinchSteps, RAIL_PX, WheelSteps, ZOOM_STEPS, zoomLabel, type Zoom } from "@/shared/zoom";
import { apply, flatToIso, invert, isoBounds, isoScene, wallOutline, type Affine, type IsoScene, type Mat } from "./iso";
import { badgePlaces, spread, type Rect } from "./layout";

const PAD = 20;            // px вокруг развёртки
const RULER_X = 64;        // px под полом: отступы
const RULER_Y = 58;        // px справа: высоты
const HEAD = 8;            // px над потолком
const PAGER = 52;          // px сверху: пейджер стен (Viewer) — над развёрткой
const MAP = { w: 264, h: 250 };  // мини-схема внизу слева (WallMap, 240 px и поля) — место под неё
const LABEL_PX = 11;       // подписи размеров
const BADGE_PX = 12;       // номер точки
const SYMBOL_MM = 34;      // радиус подрозетника Ø68
const PITCH_MM = 71;       // шаг постов в рамке
const MIN_R = 5;           // px: символ не мельче
const ISO_PAD = 28;        // px вокруг изометрии: плашки номеров
const SIDE_ALPHA = 0.45;   // соседняя стена в изометрии — полупрозрачная
const SWITCHES = new Set(["switch", "pass_switch"]);
const LOW = new Set(["data", "tv"]);

const INK = "#29251f", GREY = "#9a9288", LIGHT = "#d9d3c8", BACK = "#b0a99d";
const CHASE = "#e4ded3", CHASE_LOW = "#cfe3f3", BOX = "#b3261e", LOW_INK = "#1f6fb2";

interface Hit { key: string; r: Rect; inv: Affine | null }  // inv — экран → плоский вид стены

export type ElevMode = "flat" | "iso";

// Как рисовать стену: видимая часть from…to (мм), контур (мм; волна обрыва — у соседа) и
// обрезать ли по нему, шкалы размеров и с какой стороны высоты (null — без шкал), выводы с
// обратной стороны, заливка
interface WallOpts {
  from: number; to: number; outline: XY[] | null; clip: boolean;
  rulers: "right" | "left" | null; back: boolean; alpha: number; shade: number;
}

export class ElevationView {
  onZoom: (zoom: Zoom) => void = () => {};
  private ctx: CanvasRenderingContext2D;
  private step = 0;  // шаг масштаба (zoom.ts)
  private readonly wheel = new WheelSteps();
  private readonly pinchSteps = new PinchSteps();
  private readonly glide = new Glide();
  private w = 1; private h = 1; private dpr = 1;
  private scale = 1; private fitScale = 1; private ox = 0; private oy = 0;  // экран = o + мм·scale (y вверх)
  private drag: { x: number; y: number; ox: number; oy: number } | null = null;
  private down: { x: number; y: number } | null = null;
  private hits: Hit[] = [];
  private iso: IsoScene | null = null;  // изометрия; null — плоская развёртка
  private inv: Affine | null = null;    // пока рисуется стена изометрии — экран → её плоский вид
  private readonly font: string;
  private readonly cleanup: (() => void)[] = [];
  private readonly pinch = new Pinch();

  constructor(private readonly canvas: HTMLCanvasElement, private readonly wrap: HTMLElement,
              private data: Elevation, private withMap: boolean, mode: ElevMode = "flat") {
    this.ctx = canvas.getContext("2d")!;
    this.iso = mode === "iso" ? isoScene(data) : null;
    this.font = getComputedStyle(document.body).fontFamily || "sans-serif";
    const resize = new ResizeObserver(() => { this.resize(); this.fit(); });
    resize.observe(wrap);
    this.cleanup.push(() => resize.disconnect());
    let seen: unknown[] = [];
    this.cleanup.push(view.subscribe(() => {
      const s = view.get();
      const now = [s.hover, s.lit, s.pinned, s.themeTick];
      if (now.some((v, i) => v !== seen[i])) { seen = now; this.draw(); }
    }));
    this.bind();
  }

  destroy() { for (const f of this.cleanup) f(); }

  setData(data: Elevation, withMap: boolean, mode: ElevMode) {
    this.data = data; this.withMap = withMap;
    this.iso = mode === "iso" ? isoScene(data) : null;
    this.fit();
  }

  private resize() {
    const r = this.wrap.getBoundingClientRect();
    this.w = r.width; this.h = r.height;
    this.dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(r.width * this.dpr);
    this.canvas.height = Math.round(r.height * this.dpr);
  }

  // Вся стена с подписями; место под мини-схему — слева или снизу, где развёртка крупнее
  fit() {
    const d = this.data;
    this.glide.stop();
    // Рамка в мм экрана и поля под подписи в px: у плоской — шкалы снизу и справа
    const [X0, Y0, X1, Y1] = this.iso ? isoBounds(this.iso) : [0, 0, d.length, d.top];
    // Изометрия: отступы — под полом, высоты — у дальнего от угла края стены
    const [pl, pr, pt, pb] = !this.iso ? [0, RULER_Y, HEAD, RULER_X]
      : this.iso.corner === "left" ? [ISO_PAD, RULER_Y, ISO_PAD, RULER_X] : [RULER_Y, ISO_PAD, ISO_PAD, RULER_X];
    const W = X1 - X0, H = Y1 - Y0;
    const room = (left: number, bottom: number) =>
      Math.min((this.w - 2 * PAD - RAIL_PX - pl - pr - left) / W, (this.h - 2 * PAD - PAGER - pt - pb - bottom) / H);
    const options: [number, number][] = this.withMap && this.w > 560 ? [[MAP.w, 0], [0, MAP.h]] : [[0, 0]];
    const [left, bottom] = options.reduce((a, b) => (room(...b) > room(...a) ? b : a));
    this.scale = FIT_SHRINK * Math.max(room(left, bottom), 1e-3);
    this.fitScale = this.scale;
    this.step = 0;
    const bw = W * this.scale + pl + pr, bh = H * this.scale + pt + pb;
    this.ox = left + PAD + (this.w - RAIL_PX - left - 2 * PAD - bw) / 2 + pl - X0 * this.scale;
    this.oy = PAD + PAGER + pt + (this.h - PAGER - bottom - 2 * PAD - bh) / 2 + Y1 * this.scale;
    this.draw();
  }

  // Соседний шаг масштаба у точки (x, y) экрана; за крайние — нет
  zoomStep(dir: number, x = this.cx(), y = this.h / 2) { this.zoomTo(this.step + dir, x, y); }

  // Шаг масштаба — плавно, точка (x, y) экрана стоит на месте
  zoomTo(step: number, x = this.cx(), y = this.h / 2) {
    step = clampStep(step);
    if (step === this.step) return;
    this.step = step;
    this.glide.run({ scale: this.scale, ox: this.ox, oy: this.oy }, this.fitScale * ZOOM_STEPS[step], x, y, (v) => { Object.assign(this, v); this.draw(); });
  }

  private cx = () => (this.w - RAIL_PX) / 2;

  private sx = (x: number) => this.ox + x * this.scale;
  private sy = (y: number) => this.oy - y * this.scale;

  private on<K extends keyof HTMLElementEventMap>(type: K, fn: (ev: HTMLElementEventMap[K]) => void,
                                                  opts?: AddEventListenerOptions) {
    this.canvas.addEventListener(type, fn as EventListener, opts);
    this.cleanup.push(() => this.canvas.removeEventListener(type, fn as EventListener));
  }

  private hitAt(ev: { clientX: number; clientY: number }): string | null {
    const r = this.canvas.getBoundingClientRect();
    const x = ev.clientX - r.left, y = ev.clientY - r.top;
    // Сверху — нарисованное позже (точки поверх коробок)
    for (let k = this.hits.length - 1; k >= 0; k--) {
      const { r: [x0, y0, x1, y1], inv } = this.hits[k];
      const [hx, hy] = inv ? apply(inv, x, y) : [x, y];
      if (hx >= x0 - 3 && hx <= x1 + 3 && hy >= y0 - 3 && hy <= y1 + 3) return this.hits[k].key;
    }
    return null;
  }

  private bind() {
    this.on("wheel", (ev) => {
      ev.preventDefault();
      const r = this.canvas.getBoundingClientRect();
      const dir = this.wheel.push(ev.deltaY, performance.now());
      if (dir) this.zoomStep(dir, ev.clientX - r.left, ev.clientY - r.top);
    }, { passive: false });
    this.on("pointerdown", (ev) => {
      this.canvas.setPointerCapture(ev.pointerId);
      if (this.pinch.down(ev)) { this.drag = null; this.down = null; return; }
      this.drag = { x: ev.clientX, y: ev.clientY, ox: this.ox, oy: this.oy };
      this.down = { x: ev.clientX, y: ev.clientY };
    });
    this.on("pointermove", (ev) => {
      const step = this.pinch.move(ev, this.canvas.getBoundingClientRect());
      if (step) {
        this.ox += step.dx; this.oy += step.dy;
        const dir = this.pinchSteps.push(step.f);
        if (dir) this.zoomStep(dir, step.x, step.y); else this.draw();
        return;
      }
      if (this.drag && !this.pinch.busy && (ev.buttons & 1)) {
        if (Math.hypot(ev.clientX - this.drag.x, ev.clientY - this.drag.y) > 3) this.canvas.classList.add("drag");
        this.ox = this.drag.ox + ev.clientX - this.drag.x;
        this.oy = this.drag.oy + ev.clientY - this.drag.y;
        this.draw();
        return;
      }
      const key = this.hitAt(ev);
      this.canvas.style.cursor = key ? "pointer" : "";
      if (key !== view.get().hover) view.set({ hover: key });
    });
    const end = () => { this.drag = null; this.canvas.classList.remove("drag"); };
    // Клик без сдвига — закрепить объект (строка в панели) или снять
    this.on("pointerup", (ev) => {
      this.pinch.up(ev);
      const d = this.pinch.used ? null : this.down;
      this.down = null;
      end();
      if (!d || Math.hypot(ev.clientX - d.x, ev.clientY - d.y) > 4) return;
      view.set({ pinned: this.hitAt(ev) });
    });
    this.on("pointercancel", (ev) => { this.pinch.up(ev); end(); });
    this.on("pointerleave", () => { if (view.get().hover) view.set({ hover: null }); });
    this.on("dblclick", () => this.fit());
  }

  private lit(): Set<string> {
    const { lit, hover, pinned } = view.get();
    const out = new Set(lit || []);
    if (hover) out.add(hover);
    if (pinned) out.add(pinned);
    return out;
  }

  draw() {
    refreshPalette();
    const { ctx } = this;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.fillStyle = palette.paper || "#ffffff";
    ctx.fillRect(0, 0, this.w, this.h);
    this.hits = [];
    const d = this.data;
    if (this.iso) this.paintIso(this.iso, this.lit());
    else this.paintWall(d, this.lit(), { from: 0, to: d.length, outline: null, clip: false, rulers: "right", back: true, alpha: 1, shade: 0 });
    this.onZoom({ step: this.step, label: zoomLabel(this.step), pxPerMm: this.scale });
  }

  private text(s: string, x: number, y: number, px: number, color: string,
               align: CanvasTextAlign = "left", angle = 0) {
    const { ctx } = this;
    ctx.save();
    ctx.translate(x, y);
    if (angle) ctx.rotate(angle);
    ctx.font = `${px}px ${this.font}`;
    ctx.fillStyle = screenColor(color);
    ctx.textAlign = align; ctx.textBaseline = "middle";
    ctx.fillText(s, 0, 0);
    ctx.restore();
  }

  private line(x0: number, y0: number, x1: number, y1: number, color: string, width = 1, dash?: number[]) {
    const { ctx } = this;
    ctx.save();
    ctx.strokeStyle = screenColor(color); ctx.lineWidth = width;
    if (dash) ctx.setLineDash(dash);
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
    ctx.restore();
  }

  private hit(key: string, r: Rect) { this.hits.push({ key, r, inv: this.inv }); }

  // Стена в px плоского вида (в изометрии — под матрицей плоскости): штробы, края, проёмы,
  // щит, пунктиры к шкалам, коробки, точки, шкалы, номера. Подсвеченное — последним, поверх
  private paintWall(e: ElevWall, lit: Set<string>, o: WallOpts) {
    const { ctx } = this, d = this.data, s = this.scale;
    const x0 = this.sx(o.from), x1 = this.sx(o.to), floor = this.sy(0), ceil = this.sy(d.height), top = this.sy(d.top);
    const r = Math.max(SYMBOL_MM * s, MIN_R), pitch = Math.max(PITCH_MM * s, 2 * r + 1);
    const seen = (x: number) => x >= o.from - 1 && x <= o.to + 1;
    const edge = o.rulers === "left" ? x0 : x1;  // край со шкалой высот
    const taken: Rect[] = [];
    const points = e.points.filter((p) => seen(p.x)), boxes = e.boxes.filter((b) => seen(b.x));
    const board = e.board && seen(e.board.x) ? e.board : null;
    const last = <T extends { key: string }>(xs: T[]) => [...xs.filter((x) => !lit.has(x.key)), ...xs.filter((x) => lit.has(x.key))];

    ctx.save();
    ctx.globalAlpha = o.alpha;
    // Контур стены — заливка и обрезка (у соседа с обрывом — волной)
    if (o.outline) {
      ctx.beginPath();
      o.outline.forEach(([x, y], i) => (i ? ctx.lineTo(this.sx(x), this.sy(y)) : ctx.moveTo(this.sx(x), this.sy(y))));
      ctx.closePath();
      if (o.shade) { ctx.fillStyle = screenColor(INK); ctx.globalAlpha = o.alpha * o.shade; ctx.fill(); ctx.globalAlpha = o.alpha; }
      ctx.save();
      ctx.strokeStyle = screenColor(INK); ctx.lineWidth = 1.4; ctx.stroke();
      ctx.restore();
      if (o.clip) ctx.clip();
    }

    // Штробы — под всем
    for (const c of e.chases) {
      const half = Math.max(((c.wide ? 50 : 30) / 2) * s, 1.5);
      ctx.fillStyle = screenColor(c.low ? CHASE_LOW : CHASE);
      ctx.fillRect(this.sx(c.x) - half, this.sy(c.y1), 2 * half, (c.y1 - c.y0) * s);
    }

    // Стена: пол и потолок толще, торцы — углы помещения
    this.line(x0, floor, x1, floor, INK, 2.5);
    this.line(x0, ceil, x1, ceil, INK, 2.5);
    if (!o.outline) {
      this.line(x0, top, x0, floor, INK, 1.4);
      this.line(x1, top, x1, floor, INK, 1.4);
    }

    for (const op of e.openings) {
      const a = this.sx(op.x0), b = this.sx(op.x1), y0 = this.sy(op.y0), y1 = this.sy(op.y1);
      const color = op.assumed ? GREY : INK;
      ctx.fillStyle = palette.paper || "#ffffff";
      ctx.fillRect(a, y1, b - a, y0 - y1);
      ctx.strokeStyle = screenColor(color); ctx.lineWidth = 1.4;
      ctx.strokeRect(a, y1, b - a, y0 - y1);
      if (op.kind === "window") this.line((a + b) / 2, y0, (a + b) / 2, y1, color);
      if (op.kind === "door") {
        this.line(a, y0, (a + b) / 2, y1, LIGHT);
        this.line(b, y0, (a + b) / 2, y1, LIGHT);
      }
      if (op.assumed) this.text("*", b - 3, y1 + 8, LABEL_PX, color, "right");
    }

    if (board) {
      const b = board;
      const a = this.sx(b.x - b.width / 2), c = this.sx(b.x + b.width / 2);
      const y1 = this.sy(b.y + b.height / 2), y0 = this.sy(b.y - b.height / 2);
      const on = lit.has(b.key);
      ctx.fillStyle = palette.paper || "#ffffff";
      ctx.fillRect(a, y1, c - a, y0 - y1);
      ctx.strokeStyle = on ? palette.hl : screenColor(INK); ctx.lineWidth = on ? 3 : 1.4;
      ctx.strokeRect(a, y1, c - a, y0 - y1);
      this.text(b.name, (a + c) / 2, (y0 + y1) / 2, BADGE_PX, on ? palette.hl : INK, "center");
      taken.push([a, y1, c, y0]);
      this.hit(b.key, [a, y1, c, y0]);
    }

    // Выводы с обратной стороны — бледно, без размеров
    if (o.back) for (const p of d.back) this.symbol(p.type, p.posts, this.sx(p.x), this.sy(p.y), r, pitch, BACK, 1, false);

    // Пунктир от точек к шкалам — под символами
    if (o.rulers) {
      for (const p of last(points)) {
        const cx = this.sx(p.x), cy = this.sy(p.y), half = r + (pitch * (p.posts - 1)) / 2;
        const on = lit.has(p.key);
        const color = on ? palette.hl : GREY;
        this.line(cx, cy + r, cx, floor, color, on ? 1.2 : 0.8, [3, 3]);
        this.line(o.rulers === "left" ? cx - half : cx + half, cy, edge, cy, color, on ? 1.2 : 0.8, [3, 3]);
      }
    }

    const boxRects = new Map<string, Rect>();
    for (const b of last(boxes)) {
      const cx = this.sx(b.x), cy = this.sy(b.y), half = Math.max((b.size / 2) * s, 4);
      const on = lit.has(b.key);
      ctx.fillStyle = palette.paper || "#ffffff";
      ctx.fillRect(cx - half, cy - half, 2 * half, 2 * half);
      ctx.strokeStyle = on ? palette.hl : BOX; ctx.lineWidth = on ? 3 : 1.6;
      ctx.strokeRect(cx - half, cy - half, 2 * half, 2 * half);
      const box: Rect = [cx - half, cy - half, cx + half, cy + half];
      taken.push(box);
      boxRects.set(b.key, box);
      this.hit(b.key, box);
    }

    // Точки: пост рамки — свой символ; обводка — цвет группы, подсвеченная — толще
    const blocks = new Map<string, Rect>();
    for (const p of last(points)) {
      const cx = this.sx(p.x), cy = this.sy(p.y), half = r + (pitch * (p.posts - 1)) / 2;
      const on = lit.has(p.key);
      if (on) {
        ctx.fillStyle = palette.hl; ctx.globalAlpha = 0.18 * o.alpha;
        ctx.beginPath(); ctx.roundRect(cx - half - 5, cy - r - 5, 2 * half + 10, 2 * r + 10, r + 5); ctx.fill();
        ctx.globalAlpha = o.alpha;
      }
      const color = on ? palette.hl : LOW.has(p.type) ? LOW_INK : INK;
      this.symbol(p.type, p.posts, cx, cy, r, pitch, color, on ? 2.4 : 1.4, true);
      const rect: Rect = [cx - half, cy - r, cx + half, cy + r];
      taken.push(rect);
      blocks.set(p.key, rect);
      this.hit(p.key, rect);
    }

    // Шкалы — до номеров: их место занято
    if (o.rulers) taken.push(this.ordinatesX(e, floor, x0, x1), this.ordinatesY(e, edge, floor, top, o.rulers === "left" ? -1 : 1));

    // Номера: плашка цвета группы у символа, где свободно (места — в порядке модели, чтобы не
    // прыгали); рисуются подсвеченные последними — поверх тех, что их закрывали
    ctx.font = `600 ${BADGE_PX}px ${this.font}`;
    const labels = [
      ...points.map((p) => ({ key: p.key, text: String(p.n), color: p.color || INK, box: false, anchor: blocks.get(p.key)! })),
      ...boxes.map((b) => ({ key: b.key, text: b.label, color: BOX, box: true, anchor: boxRects.get(b.key)! })),
    ].map((l) => ({ ...l, w: ctx.measureText(l.text).width + 10 }));
    const places = badgePlaces(labels, BADGE_PX + 6, taken);
    for (const l of last(labels.map((l, k) => ({ ...l, at: places[k] })))) {
      const on = lit.has(l.key);
      if (l.box) this.text(l.text, (l.at[0] + l.at[2]) / 2, (l.at[1] + l.at[3]) / 2, BADGE_PX, on ? palette.hl : BOX, "center");
      else this.badge(l.text, l.at, on ? palette.hl : l.color, on);
      this.hit(l.key, l.at);
    }
    // Номера выводов той стороны — бледно, после своих
    if (o.back) {
      for (const p of d.back) {
        const cx = this.sx(p.x) + r + (pitch * (p.posts - 1)) / 2 + 3;
        this.text(String(p.n), cx, this.sy(p.y), LABEL_PX, BACK);
      }
    }
    ctx.restore();
  }

  private symbol(type: string, posts: number, cx: number, cy: number, r: number, pitch: number,
                 color: string, width: number, fill: boolean) {
    const { ctx } = this;
    const first = cx - (pitch * (posts - 1)) / 2;
    ctx.strokeStyle = screenColor(color); ctx.lineWidth = width;
    ctx.fillStyle = palette.paper || "#ffffff";
    for (let k = 0; k < posts; k++) {
      const x = first + k * pitch;
      ctx.beginPath();
      if (SWITCHES.has(type)) ctx.rect(x - r, cy - r, 2 * r, 2 * r);
      else ctx.arc(x, cy, r, 0, 2 * Math.PI);
      if (fill) ctx.fill();
      ctx.stroke();
    }
  }

  private badge(s: string, [x0, y0, x1, y1]: Rect, color: string, on: boolean) {
    const { ctx } = this;
    ctx.fillStyle = screenColor(color);
    ctx.beginPath(); ctx.roundRect(x0, y0, x1 - x0, y1 - y0, (y1 - y0) / 2); ctx.fill();
    if (on) { ctx.strokeStyle = palette.paper || "#fff"; ctx.lineWidth = 1.5; ctx.stroke(); }
    ctx.font = `600 ${BADGE_PX}px ${this.font}`;
    ctx.fillStyle = "#ffffff";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(s, (x0 + x1) / 2, (y0 + y1) / 2 + 0.5);
  }

  private toScreen = ([X, Y]: XY): XY => [this.ox + X * this.scale, this.oy - Y * this.scale];

  // Рисунок плоского вида стены — на её плоскости в изометрии (и попадания — через обратное)
  private onWall(m: Mat, draw: () => void) {
    const { ctx } = this, t = flatToIso(m, this.scale, this.ox, this.oy);
    ctx.save();
    ctx.transform(...t);
    this.inv = invert(t);
    draw();
    this.inv = null;
    ctx.restore();
  }

  // Изометрия: пол у стен, сосед в углу (полупрозрачный, без шкал, обрыв — волной), стена
  // развёртки со шкалами у дальнего от угла края
  private paintIso(iso: IsoScene, lit: Set<string>) {
    const { ctx } = this, d = this.data;
    ctx.beginPath();
    iso.floor.map(this.toScreen).forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.closePath();
    ctx.fillStyle = screenColor(INK); ctx.globalAlpha = 0.05; ctx.fill(); ctx.globalAlpha = 1;
    const side = iso.side;
    if (side) {
      this.onWall(side.mat, () => this.paintWall(side.wall, lit, {
        from: side.from, to: side.to, outline: wallOutline(side, 6 / this.scale), clip: true,
        rulers: null, back: false, alpha: SIDE_ALPHA, shade: 0.1,
      }));
    }
    this.onWall(iso.main.mat, () => this.paintWall(d, lit, {
      from: 0, to: d.length, outline: wallOutline(iso.main, 0), clip: false,
      rulers: iso.corner === "left" ? "right" : "left", back: true, alpha: 1, shade: 0.03,
    }));
  }

  // Отступы от левого угла — под полом, вертикально, разведены; занятая полоса
  private ordinatesX(d: ElevWall, floor: number, x0: number, x1: number): Rect {
    const xs = new Set<number>([0, d.length]);
    for (const p of d.points) xs.add(Math.round(p.x));
    for (const b of d.boxes) xs.add(Math.round(b.x));
    if (d.board) xs.add(Math.round(d.board.x));
    const values = [...xs].sort((a, b) => a - b);
    const wanted = values.map((v) => this.sx(v));
    const places = spread(wanted, LABEL_PX + 3, x0 - LABEL_PX, x1 + LABEL_PX);
    const tick = 5, jog = 8;
    values.forEach((v, k) => {
      this.line(wanted[k], floor, wanted[k], floor + tick, INK, 0.8);
      this.line(wanted[k], floor + tick, places[k], floor + tick + jog, INK, 0.8);
      this.text(`${v}`, places[k], floor + tick + jog + 3, LABEL_PX, INK, "right", -Math.PI / 2);
    });
    return [x0 - LABEL_PX, floor, x1 + LABEL_PX, floor + RULER_X];
  }

  // Высоты от пола — справа (dir 1) или слева (-1); потолок со «*», если высота — допущение
  private ordinatesY(d: ElevWall, edge: number, floor: number, top: number, dir: 1 | -1): Rect {
    const { height, height_assumed } = this.data;
    const ys = new Set<number>([height]);
    for (const p of d.points) ys.add(Math.round(p.y));
    for (const b of d.boxes) ys.add(Math.round(b.y));
    if (d.board) ys.add(Math.round(d.board.y));
    const values = [...ys].sort((a, b) => b - a);  // сверху вниз — по экрану по возрастанию
    const wanted = values.map((v) => this.sy(v));
    const places = spread(wanted, LABEL_PX + 3, top - LABEL_PX, floor);
    const tick = 5, jog = 8;
    values.forEach((v, k) => {
      this.line(edge, wanted[k], edge + dir * tick, wanted[k], INK, 0.8);
      this.line(edge + dir * tick, wanted[k], edge + dir * (tick + jog), places[k], INK, 0.8);
      const mark = v === height && height_assumed ? "*" : "";
      this.text(`${v}${mark}`, edge + dir * (tick + jog + 3), places[k], LABEL_PX, INK, dir > 0 ? "left" : "right");
    });
    return dir > 0 ? [edge, top - LABEL_PX, edge + RULER_Y, floor + LABEL_PX] : [edge - RULER_Y, top - LABEL_PX, edge, floor + LABEL_PX];
  }
}
