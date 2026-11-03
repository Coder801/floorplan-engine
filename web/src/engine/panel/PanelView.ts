// Щит в лицо в своём canvas: рисуется из данных щита (ключ panel страницы), а не из
// примитивов листа. Корпус — реальный щит каталога в натуральную величину (enclosure),
// аппараты — отрисовщиками каталога по модели. Рейки по видам (layout.ts):
// общие аппараты, автоматы на гребёнке, дифавтоматы на двойной гребёнке (L + N). Питание
// сверху: ввод → реле перемычкой по нижним клеммам, с выхода реле — гребёнка общих
// аппаратов и стволы вдоль левой стенки к гребёнкам рядов (основная; резервная — от АВР;
// N — от ввода N к клеммнику N и ветками к нулевым гребёнкам). Провод группы — тонкой линией
// цвета группы из нижней клеммы в пучок под рейкой, пучком в правую стенку, за корпусом — под
// углом к подписи; ввод L, N, PE сверху, клеммники PE
// вверху и N внизу корпуса. Масштаб и сдвиг; объекты под курсором не ищутся — подсветка
// только от строки таблицы в боковой панели (store.lit) и у открытой карточки (store.pinned,
// клик по аппарату или строке): аппарат и провод группы светятся. Наведённое — цветом --hl,
// свечение появляется плавно и мягко пульсирует (без анимации — ровное); закреплённое
// кликом — своим цветом --pin, ровно, без пульсации: ховер на других строках его не трогает. У гибридного инвертора — щит АКБ:
// провода АКБ и строк панелей — вверх в вводы BAT и PV инвертора, АКБ под щитом.

import { Pinch } from "@/engine/sheet/pinch";
import { FIT_SHRINK, REDUCED_MOTION, VIEW_PAD } from "@/shared/consts";
import { palette, refreshPalette, screenColor } from "@/shared/palette";
import { view } from "@/shared/store";
import type { PanelData } from "@/shared/types";
import { clampStep, Glide, PinchSteps, RAIL_PX, WheelSteps, ZOOM_STEPS, zoomLabel, type Zoom } from "@/shared/zoom";
import { clip, plate, rendererFor, SCREW, shade, text, type Pen } from "./catalog";
import { BACKUP, busSegments, CHAIN, groupPath, LABEL_STEP, LABELS, layout, MODULE, TERM, termX,
         type PanelLayout, type Placed, type Rect, type Row } from "./layout";

const WIRE = 2.2;          // толщина провода, мм щита
const INPUT_WIRE = "#8b4513";
const RESERVE = "#2e8b57";
const PE = "#2e8b2e";
const PE_STRIPE = "#e3c200";  // PE — жёлто-зелёный
// Нутро корпуса — светлое в любой теме, как настоящий щит: заливка, гребёнки и подложка
// проводов внутри — цветами светлой темы, а не screenColor
const INSIDE = "#ededeb", INSIDE_HALO = "#ffffff", COMB = "#5a5a5a";
const N = "#1f5fbf";
const PE_BODY = "#3f9b4a";    // корпус клеммника PE
const N_BODY = "#2f6fc4";     // корпус клеммника N
const LABEL = 7;           // подписи у проводов, мм щита
const ID = 4.4;            // обозначение на табличке аппарата
// Над аппаратами: фазная гребёнка, нулевая (у дифавтоматов), подход резервного питания
const L_COMB = 5, N_COMB = 10;
const approach = (row: Row) => row.devTop - (row.kind === "double" ? 15 : 11);
// Под общими аппаратами — полосы перемычек: N ввода, ввод → реле и гребёнка общих,
// ствол основной сети, ствол резерва, PE ПЗІП (ниже — питание инвертора, layout.FEED_LANE)
const BELOW = { n: 2.5, chain: 5.5, main: 8.5, reserve: 11.5, spd: 14.5 } as const;
// Стволы вдоль левой стенки (левее аппаратов дорожек групп нет)
const TRUNK = { n: 10, main: 18, reserve: 26, spd: 4 } as const;
// Питание инвертора: N — под L; PE инвертора — стволом вдоль правой стенки (от неё — PE_TRUNK)
const CORE = 2.5;
const PE_TRUNK = 8;
const GROUP_WIRE = 1.4;    // провод группы, мм щита: не толще шага пучка
const TITLE = 9;
const DC_PLUS = "#c62828", DC_MINUS = "#1e1e1e";  // провода DC: «+» красный, «−» чёрный
const GLOW_IN = 180;       // мс: появление свечения
const GLOW_PERIOD = 1400;  // мс: период пульсации

export class PanelView {
  onZoom: (zoom: Zoom) => void = () => {};
  private ctx: CanvasRenderingContext2D;
  private step = 0;  // шаг масштаба (zoom.ts)
  private readonly wheel = new WheelSteps();
  private readonly pinchSteps = new PinchSteps();
  private readonly glide = new Glide();
  private lay: PanelLayout;
  private w = 1; private h = 1; private dpr = 1;
  private scale = 1; private fitScale = 1; private ox = 0; private oy = 0;
  private drag: { x: number; y: number; ox: number; oy: number } | null = null;
  private readonly font: string;
  private readonly cleanup: (() => void)[] = [];
  private litAt = 0; private pinAt = 0; private pulse = 0;
  private down: { x: number; y: number } | null = null;
  private readonly pinch = new Pinch();

  constructor(private readonly canvas: HTMLCanvasElement, private readonly wrap: HTMLElement,
              readonly data: PanelData) {
    this.ctx = canvas.getContext("2d")!;
    this.font = getComputedStyle(document.body).fontFamily || "sans-serif";
    this.lay = layout(data);
    const resize = new ResizeObserver(() => { this.resize(); this.fit(); });
    resize.observe(wrap);
    this.cleanup.push(() => resize.disconnect());
    let seen: unknown[] = [];
    this.cleanup.push(view.subscribe(() => {
      const s = view.get();
      const now = [s.lit, s.themeTick, s.pinned];
      if (now[0] !== seen[0]) this.litAt = performance.now();
      if (now[2] !== seen[2]) this.pinAt = performance.now();
      if (now.some((v, i) => v !== seen[i])) { seen = now; this.draw(); }
    }));
    this.bind();
  }

  // Наведённое: строка таблицы под курсором, кроме закреплённого — оно светится своим цветом
  private hoverKeys(): Set<string> {
    const { lit, pinned } = view.get();
    const out = new Set(lit || []);
    if (pinned) out.delete(pinned);
    return out;
  }

  // Аппараты щита и щита АКБ — для клика и подсветки
  private allPlaced(): Placed[] { return [...this.lay.placed, ...(this.lay.dc?.placed || [])]; }

  destroy() { cancelAnimationFrame(this.pulse); for (const f of this.cleanup) f(); }

  private resize() {
    const r = this.wrap.getBoundingClientRect();
    this.w = r.width; this.h = r.height;
    this.dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(r.width * this.dpr);
    this.canvas.height = Math.round(r.height * this.dpr);
  }

  fit() {
    this.glide.stop();
    const l = this.lay, top = -TITLE * 2;  // заголовок над вводом
    this.scale = FIT_SHRINK * Math.min((this.w - RAIL_PX - 2 * VIEW_PAD) / l.width, (this.h - 2 * VIEW_PAD) / (l.height - top));
    this.fitScale = this.scale;
    this.step = 0;
    this.ox = (this.w - RAIL_PX - l.width * this.scale) / 2;
    this.oy = (this.h - (l.height + top) * this.scale) / 2;
    this.draw();
  }

  // Соседний шаг масштаба у точки (x, y) экрана; за крайние — нет
  zoomStep(dir: number, x = (this.w - RAIL_PX) / 2, y = this.h / 2) { this.zoomTo(this.step + dir, x, y); }

  // Шаг масштаба — плавно, точка (x, y) экрана стоит на месте
  zoomTo(step: number, x = (this.w - RAIL_PX) / 2, y = this.h / 2) {
    step = clampStep(step);
    if (step === this.step) return;
    this.step = step;
    this.glide.run({ scale: this.scale, ox: this.ox, oy: this.oy }, this.fitScale * ZOOM_STEPS[step], x, y, (v) => { Object.assign(this, v); this.draw(); });
  }

  private on<K extends keyof HTMLElementEventMap>(type: K, fn: (ev: HTMLElementEventMap[K]) => void,
                                                  opts?: AddEventListenerOptions) {
    this.canvas.addEventListener(type, fn as EventListener, opts);
    this.cleanup.push(() => this.canvas.removeEventListener(type, fn as EventListener));
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
      if (this.pinch.down(ev)) { this.drag = null; this.down = null; return; }  // щипок, не сдвиг
      this.drag = { x: ev.clientX, y: ev.clientY, ox: this.ox, oy: this.oy };
      this.down = { x: ev.clientX, y: ev.clientY };
      this.canvas.setPointerCapture(ev.pointerId);
      this.canvas.classList.add("drag");
    });
    this.on("pointermove", (ev) => {
      const step = this.pinch.move(ev, this.canvas.getBoundingClientRect());
      if (step) {
        this.ox += step.dx; this.oy += step.dy;
        const dir = this.pinchSteps.push(step.f);
        if (dir) this.zoomStep(dir, step.x, step.y); else this.draw();
        return;
      }
      if (!this.drag || this.pinch.busy) return;
      this.ox = this.drag.ox + ev.clientX - this.drag.x;
      this.oy = this.drag.oy + ev.clientY - this.drag.y;
      this.draw();
    });
    const end = () => { this.drag = null; this.canvas.classList.remove("drag"); };
    // Клик (без сдвига) — карточка аппарата под курсором; мимо аппаратов — закрыть
    this.on("pointerup", (ev) => {
      this.pinch.up(ev);
      const d = this.pinch.used ? null : this.down;  // конец щипка — не клик
      this.down = null;
      end();
      if (!d || Math.hypot(ev.clientX - d.x, ev.clientY - d.y) > 4) return;
      const r = this.canvas.getBoundingClientRect();
      const mx = (ev.clientX - r.left - this.ox) / this.scale, my = (ev.clientY - r.top - this.oy) / this.scale;
      const hit = this.allPlaced().find((p) => mx >= p.x && mx <= p.x + p.w && my >= p.y && my <= p.y + p.h);
      view.set({ pinned: hit ? hit.dev.key : null });
    });
    this.on("pointercancel", (ev) => { this.pinch.up(ev); end(); });
    this.on("dblclick", () => this.fit());
  }

  draw() {
    refreshPalette();
    const { ctx } = this;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.fillStyle = palette.paper || "#ffffff";
    ctx.fillRect(0, 0, this.w, this.h);
    ctx.setTransform(this.dpr * this.scale, 0, 0, this.dpr * this.scale, this.dpr * this.ox, this.dpr * this.oy);
    this.paint({ ctx, font: this.font, ink: screenColor("#2b2b2b") });
    // Свечение подсветки — следующий кадр, пока наведено (пульсация) или закреплённое появляется
    const fading = !!view.get().pinned && performance.now() - this.pinAt < GLOW_IN;
    if ((this.hoverKeys().size || fading) && !REDUCED_MOTION && !this.pulse) {
      this.pulse = requestAnimationFrame(() => { this.pulse = 0; this.draw(); });
    }
    this.onZoom({ step: this.step, label: zoomLabel(this.step), pxPerMm: this.scale });
  }

  // Весь щит в мм щита на текущем преобразовании
  private paint(pen: Pen) {
    const l = this.lay, d = this.data;
    const enc = l.enclosure;
    text(pen, `${d.texts.title} · ${enc.title} · ${d.totals.modules}/${enc.rows * enc.per_row} DIN`,
         0, -TITLE, TITLE, pen.ink, "left");

    const b = l.box;
    this.enclosure(pen, b, enc);
    this.terminalBlock(pen, l.pe, "PE", PE_BODY);
    this.terminalBlock(pen, l.n, "N", N_BODY);

    const byId = new Map(l.placed.map((p) => [p.dev.id, p]));
    for (const y of l.rails) this.rail(pen, b.x + 12, b.x + b.w - 12, y);  // и пустые
    l.rows.forEach((row, r) => {
      const placed = l.placed.filter((p) => p.row === r);
      for (const [x0, x1, reserve] of busSegments(placed)) {
        if (reserve) this.reserveFrame(pen, x0, x1, row.top, row.gutterTop + 4);
      }
      for (const p of placed) this.device(pen, p);
      if (row.kind === "common") this.commonComb(placed, row);
      else this.combs(placed, row);
    });
    this.feeds();
    for (const p of l.placed) this.outWire(pen, p);

    // Ввод сверху: L и N — в вводной автомат, PE — в вводную клемму клеммника PE
    const qs = byId.get("QS1");
    const peX = termX(l.pe, 0);
    this.wire(PE, [[peX, 0], [peX, l.pe.y + 6]], PE_STRIPE);
    if (qs) {
      const lx = qs.x + MODULE / 2, nx = qs.x + 1.5 * MODULE;
      this.wire(INPUT_WIRE, [[lx, 0], [lx, qs.y + SCREW]]);
      this.wire(N, [[nx, 0], [nx, qs.y + SCREW]]);
      text(pen, d.texts.grid, nx + 6, 12, LABEL, pen.ink, "left");
    }
    if (l.external && d.external) this.external(pen, byId);
    this.highlight(pen);
  }

  // Корпус: пластик щита и монтажное поле внутри, габарит под ним
  private enclosure(pen: Pen, b: Rect, enc: PanelLayout["enclosure"]) {
    const { ctx } = pen;
    ctx.fillStyle = enc.body;
    ctx.strokeStyle = pen.ink; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.roundRect(b.x, b.y, b.w, b.h, 8); ctx.fill(); ctx.stroke();
    ctx.fillStyle = INSIDE; ctx.strokeStyle = "#b9b9b5"; ctx.lineWidth = 0.8;
    ctx.beginPath(); ctx.roundRect(b.x + 3, b.y + 3, b.w - 6, b.h - 6, 6); ctx.fill(); ctx.stroke();
    text(pen, `${enc.width} × ${enc.height} мм`, b.x + b.w, b.y + b.h + 7, 5, pen.ink, "right");
  }

  private device(pen: Pen, p: Placed) {
    const { ctx } = pen, dev = p.dev;
    rendererFor(dev)(pen, dev, p);
    // Маркировка на табличке крышки: обозначение на цвете группы — как её линии на листах
    const color = (dev.group && this.data.groups[dev.group]?.color) || null;
    const t = plate(p);
    if (color) { ctx.fillStyle = color; ctx.fillRect(t.x, t.y, t.w, t.h); }
    // Узкая табличка: сначала без «*» (допущение видно в подписи группы), потом мельче
    ctx.font = `${ID}px ${pen.font}`;
    const id = dev.assumed && ctx.measureText(dev.id + "*").width <= t.w ? dev.id + "*" : dev.id;
    const size = Math.min(ID, (ID * t.w) / ctx.measureText(id).width);
    text(pen, id, t.x + t.w / 2, t.y + t.h / 2 + 0.2, size, color && dark(color) ? "#ffffff" : "#1e1e1e");
    if (dev.kind === "spd") {  // ПЗІП — на клеммник PE
      // Вдоль левой стенки вверх и по просвету под клеммником — дорожки групп не пересекает
      const pe = this.lay.pe, cx = p.x + p.w / 2, x = termX(pe, 1);
      const y = this.lay.rows[p.row].gutterTop + BELOW.spd, band = pe.y + pe.h + 6, side = TRUNK.spd;
      this.wire(PE, [[cx, p.y + p.h - SCREW], [cx, y], [side, y], [side, band], [x, band], [x, pe.y + pe.h - 6]],
                PE_STRIPE);
    }
  }

  // Провод группы — тонкой линией цвета группы по пучку (groupPath), подпись — в колонке
  // справа. Питание инвертора — L и N той же дорожкой, дальше к инвертору (external)
  private outWire(pen: Pen, p: Placed) {
    if (p.lane === null) return;
    const g = p.dev.group ? this.data.groups[p.dev.group] : undefined;
    const cx = p.x + MODULE / 2, right = this.lay.box.x + this.lay.box.w, from = p.y + p.h - SCREW;
    if (!g) {  // питание инвертора 2P
      const nx = p.x + 1.5 * MODULE;
      this.wire(N, [[nx, from], [nx, p.lane + CORE], [right, p.lane + CORE]]);
      this.wire(INPUT_WIRE, [[cx, from], [cx, p.lane], [right, p.lane]]);
      return;
    }
    const color = g.color || pen.ink;
    const pts = groupPath(this.lay, p);
    this.wire(color, pts, undefined, Math.min(GROUP_WIRE, this.lay.rows[p.row].pitch * 0.7));
    if (p.label === null) return;
    const { ctx } = pen, [ex, ey] = pts[pts.length - 1];
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(ex, ey, 1.4, 0, 2 * Math.PI); ctx.fill();
    // «QF6 Освітлення — Санвузол · 3x1.5 · 0,50 кВт*»: назначение — чернилами, кабель и
    // мощность — цветом группы
    const tail = ` · ${g.cable || "—"} · ${(g.power / 1000).toFixed(2).replace(".", ",")} кВт${g.assumed ? "*" : ""}`;
    ctx.font = `${LABEL}px ${pen.font}`;
    const room = LABELS - 8 - ctx.measureText(tail).width;
    const lead = clip(pen, `${p.dev.id}  ${g.purpose}`, room, LABEL);
    const x = this.lay.labelX + 1;
    text(pen, lead, x, p.label, LABEL, pen.ink, "left");
    ctx.font = `${LABEL}px ${pen.font}`;
    text(pen, tail, x + ctx.measureText(lead).width, p.label, LABEL, color, "left");
  }

  // Подсветка: закреплённый аппарат — ровно, цветом --pin; наведённый строкой таблицы — цветом
  // --hl, появление — GLOW_IN, дальше мягкая пульсация. Аппарат и провод его группы светятся,
  // строка подписи — мягким фоном
  private highlight(pen: Pen) {
    const now = performance.now(), { pinned } = view.get();
    const fade = (since: number) => REDUCED_MOTION ? 1 : Math.min(1, (now - since) / GLOW_IN);
    const hover = this.hoverKeys();
    const wave = REDUCED_MOTION ? 0.5 : 0.5 + 0.5 * Math.sin(((now - this.litAt) / GLOW_PERIOD) * 2 * Math.PI);
    for (const p of this.allPlaced()) {
      if (p.dev.key === pinned) this.glow(pen, p, palette.pin, fade(this.pinAt), 0.5);
      else if (hover.has(p.dev.key)) this.glow(pen, p, palette.hl, fade(this.litAt), wave);
    }
  }

  // Свечение одного аппарата: провод группы поверх, заливка с ореолом, фон строки подписи;
  // wave — 0…1, на сколько ореол и заливка «дышат» (закреплённый — константа)
  private glow(pen: Pen, p: Placed, color: string, fade: number, wave: number) {
    const { ctx } = pen;
    ctx.save();
    ctx.globalAlpha = fade;
    ctx.shadowColor = color;
    ctx.shadowBlur = (10 + 8 * wave) * this.dpr;
    if (p.lane !== null && p.dev.group) {
      ctx.strokeStyle = color; ctx.lineWidth = WIRE;
      ctx.lineJoin = "round"; ctx.lineCap = "round";
      ctx.beginPath();
      groupPath(this.lay, p).forEach(([x, y], k) => (k ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.stroke();
    }
    // Аппарат — полупрозрачной заливкой с ореолом
    ctx.fillStyle = color;
    ctx.globalAlpha = fade * (0.05 + 0.04 * wave);  // прозрачно — аппарат виден
    ctx.beginPath(); ctx.roundRect(p.x, p.y, p.w, p.h, 2); ctx.fill();
    ctx.shadowBlur = 0;
    if (p.label !== null) {
      ctx.globalAlpha = fade * 0.14;
      ctx.beginPath(); ctx.roundRect(this.lay.labelX - 2, p.label - LABEL_STEP / 2, LABELS, LABEL_STEP, 2); ctx.fill();
    }
    ctx.restore();
  }

  // DIN-рейка TS35: профиль 35 мм с отбортовкой и пазами крепления; видна у концов и в
  // промежутках между аппаратами
  private rail(pen: Pen, x0: number, x1: number, y: number) {
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

  // Гребёнки ряда групп над аппаратами: фазная (основная и резервная — участками), зубцы — в
  // верхнюю клемму первого модуля; у дифавтоматов ещё нулевая — одна на ряд, зубцы — во
  // второй модуль (N)
  private combs(placed: Placed[], row: Row) {
    const lY = row.devTop - L_COMB, nY = row.devTop - N_COMB;
    if (row.kind === "double" && placed.length) {
      for (const p of placed) this.tooth(N, p.x + 1.5 * MODULE, nY, p.y + SCREW);
      const last = placed[placed.length - 1];
      this.bar(N, placed[0].x + 3, last.x + last.w - 3, nY);
    }
    for (const [x0, x1, reserve] of busSegments(placed)) {
      const color = reserve ? RESERVE : COMB;
      this.bar(color, x0 + 3, x1 - 3, lY);
      for (const p of placed) {
        if (!!p.dev.reserve === reserve) this.tooth(color, p.x + MODULE / 2, lY, p.y + SCREW);
      }
    }
  }

  // Гребёнка общих аппаратов после ввода и реле (ПЗІП, АВР — вход I, питание инвертора);
  // выход инвертора — не от сети
  private commonComb(placed: Placed[], row: Row) {
    const xs = placed.filter((p) => !CHAIN.has(p.dev.kind) && p.dev.kind !== "output");
    if (!xs.length) return;
    const lY = row.devTop - L_COMB, color = COMB;
    const last = xs[xs.length - 1];
    this.bar(color, xs[0].x + 3, last.x + MODULE / 2 + 2, lY);
    for (const p of xs) this.tooth(color, p.x + MODULE / 2, lY, p.y + SCREW);
  }

  private bar(color: string, x0: number, x1: number, y: number) {
    const { ctx } = this;
    ctx.strokeStyle = color; ctx.lineWidth = 3; ctx.lineCap = "butt";
    ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke();
  }

  private tooth(color: string, x: number, y0: number, y1: number) {
    const { ctx } = this;
    ctx.strokeStyle = color; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(x, y0); ctx.lineTo(x, y1); ctx.stroke();
  }

  // Провод с подложкой цвета фона — на пересечении видно, какой сверху; внутри корпуса
  // подложка светлая (нутро светлое в любой теме), снаружи — цвета бумаги; stripe — полосы
  // второго цвета (PE)
  private wire(color: string, pts: [number, number][], stripe?: string, width = WIRE) {
    const { ctx } = this, boxes = [this.lay.box, ...(this.lay.dc ? [this.lay.dc.box] : [])];
    ctx.lineJoin = "round"; ctx.lineCap = "round";
    ctx.beginPath();
    pts.forEach(([x, y], k) => (k ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    // Подложка тонкого провода — уже: в пучке не закрывает соседей
    ctx.strokeStyle = palette.paper || "#ffffff"; ctx.lineWidth = width + Math.min(1.6, width * 0.4); ctx.stroke();
    ctx.save();
    const clip = new Path2D();
    for (const b of boxes) clip.roundRect(b.x, b.y, b.w, b.h, 6);
    ctx.clip(clip);
    ctx.strokeStyle = INSIDE_HALO; ctx.stroke();
    ctx.restore();
    ctx.strokeStyle = color; ctx.lineWidth = width; ctx.stroke();
    if (stripe) {
      ctx.save();
      ctx.setLineDash([5, 5]); ctx.lineCap = "butt";
      ctx.strokeStyle = stripe; ctx.stroke();
      ctx.restore();
    }
  }

  // Клеммник N / PE (как Hager QuickConnect): светлый корпус с лапками крепления и полосой
  // цвета проводника; вводная клемма — под винт, остальные безвинтовые: рычажок цвета
  // проводника сверху, круглое отверстие под провод снизу; бирка справа
  private terminalBlock(pen: Pen, r: Rect, label: string, color: string) {
    const { ctx } = pen, n = this.lay.terminals;
    const x0 = r.x + TERM.foot, x1 = r.x + r.w - TERM.foot;
    // Лапки крепления
    for (const x of [r.x, x1]) {
      ctx.fillStyle = "#b5b5b1"; ctx.strokeStyle = "#7d7d79"; ctx.lineWidth = 0.6;
      ctx.beginPath(); ctx.roundRect(x, r.y + 5, TERM.foot, r.h - 10, 1); ctx.fill(); ctx.stroke();
      ctx.fillStyle = "#7d7d79";
      ctx.beginPath(); ctx.arc(x + TERM.foot / 2, r.y + r.h / 2, 1.2, 0, 2 * Math.PI); ctx.fill();
    }
    // Корпус и полоса цвета проводника по низу
    ctx.fillStyle = "#e4e4e0"; ctx.strokeStyle = "#8a8a86"; ctx.lineWidth = 0.8;
    ctx.beginPath(); ctx.roundRect(x0, r.y, x1 - x0, r.h, 2); ctx.fill(); ctx.stroke();
    ctx.fillStyle = "#f3f3f0";
    ctx.fillRect(x0 + 1, r.y + 1, x1 - x0 - 2, 2);
    ctx.fillStyle = color;
    ctx.fillRect(x0 + 1, r.y + r.h - 3.2, x1 - x0 - 2, 2.2);
    // Вводная: винт и отверстие
    const big = termX(r, 0);
    ctx.fillStyle = "#d2d2ce";
    ctx.fillRect(big - TERM.big / 2 + 0.6, r.y + 3.5, TERM.big - 1.2, r.h - 8);
    ctx.fillStyle = "#cfcfcb"; ctx.strokeStyle = "#6b6b68"; ctx.lineWidth = 0.5;
    ctx.beginPath(); ctx.arc(big, r.y + 7.5, 3.4, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
    ctx.strokeStyle = "#4a4a48"; ctx.lineWidth = 0.7;
    ctx.beginPath(); ctx.moveTo(big - 2.2, r.y + 7.5); ctx.lineTo(big + 2.2, r.y + 7.5); ctx.stroke();
    ctx.fillStyle = "#26282a";
    ctx.beginPath(); ctx.arc(big, r.y + r.h - 8.5, 2.6, 0, 2 * Math.PI); ctx.fill();
    // Безвинтовые клеммы: перегородки, рычажок, отверстие
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
    // Бирка с маркировкой
    const tx = x1 - TERM.tag;
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.roundRect(tx + 1.5, r.y + 4, TERM.tag - 3, r.h - 9, 1); ctx.fill();
    text(pen, label, tx + TERM.tag / 2, r.y + (r.h - 1) / 2, 6, "#ffffff");
  }

  // Питание по щиту. Под общими аппаратами: ввод → реле по нижним клеммам; с выхода
  // последнего из них (у ввода — фаза в первом модуле, у реле — последний модуль) — в
  // гребёнку общих аппаратов и стволом вдоль левой стенки к фазным гребёнкам рядов групп;
  // с выхода АВР — стволом резерва к резервным участкам (подход над гребёнкой); N ввода —
  // вдоль стенки к клеммнику N, ветками — к нулевым гребёнкам дифавтоматов
  private feeds() {
    const l = this.lay, rows = l.rows;
    const common = l.placed.filter((p) => rows[p.row].kind === "common");
    const below = (p: Placed, k: keyof typeof BELOW) => rows[p.row].gutterTop + BELOW[k];
    const bottom = (p: Placed, x: number): [number, number] => [x, p.y + p.h - SCREW];
    const chain = common.filter((p) => CHAIN.has(p.dev.kind));
    chain.slice(1).forEach((q, k) => {
      const p = chain[k], out = p.x + MODULE / 2, into = q.x + MODULE / 2;
      this.wire(INPUT_WIRE, [bottom(p, out), [out, below(p, "chain")], [into, below(p, "chain")], bottom(q, into)]);
    });
    const comb = (reserve: boolean) => rows.flatMap((row, r) => row.kind === "common" ? [] :
      busSegments(l.placed.filter((p) => p.row === r)).filter((s) => s[2] === reserve)
        .map((s) => ({ row, x: s[0] + 3 })));
    const src = chain[chain.length - 1];
    if (src) {
      const out = src.dev.kind === "input" ? src.x + MODULE / 2 : src.x + src.w - MODULE / 2;
      const first = common.find((p) => !CHAIN.has(p.dev.kind));
      if (first) {
        const y = below(src, "chain"), top = rows[first.row].devTop - L_COMB;
        this.wire(INPUT_WIRE, [bottom(src, out), [out, y], [first.x, y], [first.x, top], [first.x + 3, top]]);
      }
      const y = below(src, "main");
      for (const t of comb(false)) {
        const top = t.row.devTop - L_COMB;
        this.wire(INPUT_WIRE, [bottom(src, out), [out, y], [TRUNK.main, y], [TRUNK.main, top], [t.x, top]]);
      }
    }
    const backup = common.find((p) => BACKUP.has(p.dev.kind));
    if (backup) {
      const out = backup.x + MODULE / 2, y = below(backup, "reserve");
      for (const t of comb(true)) {
        const a = approach(t.row), top = t.row.devTop - L_COMB;
        this.wire(RESERVE, [bottom(backup, out), [out, y], [TRUNK.reserve, y], [TRUNK.reserve, a], [t.x, a], [t.x, top]]);
      }
    }
    const qs = chain.find((p) => p.dev.kind === "input");
    if (qs) {
      const nx = qs.x + 1.5 * MODULE, y = below(qs, "n"), nIn = termX(l.n, 0), over = l.n.y - 6;
      this.wire(N, [bottom(qs, nx), [nx, y], [TRUNK.n, y], [TRUNK.n, over], [nIn, over], [nIn, l.n.y + 6]]);
      rows.forEach((row, r) => {
        const first = l.placed.find((p) => p.row === r);
        if (row.kind !== "double" || !first) return;
        const nY = row.devTop - N_COMB;
        this.wire(N, [[TRUNK.n, nY], [first.x + 3, nY]]);
      });
    }
  }

  private reserveFrame(pen: Pen, x0: number, x1: number, y0: number, y1: number) {
    const { ctx } = pen;
    ctx.save();
    ctx.setLineDash([6, 4]);
    ctx.strokeStyle = RESERVE; ctx.lineWidth = 1.2;
    ctx.strokeRect(x0 - 4, y0, x1 - x0 + 8, y1 - y0);
    ctx.restore();
    text(pen, this.data.texts.reserve, x0 - 2, y0 - 2.8, 4.5, RESERVE, "left");
  }

  // Инвертор или вилка генератора справа от подписей; пять проводов снизу, без пересечений:
  // GRID L, N — от питания инвертора его дорожкой; LOAD L, N — по просвету левее инвертора
  // и над рядом АВР во вход II (два последних модуля); PE — стволом вдоль правой стенки в
  // последнюю клемму клеммника PE
  private external(pen: Pen, byId: Map<string, Placed>) {
    const e = this.lay.external!, x = this.data.external!;
    const t = this.inverterBody(pen, e, x);
    const right = this.lay.box.x + this.lay.box.w, bottom = e.y + e.h;
    const feed = x.feed ? byId.get(x.feed) : undefined;
    if (feed && feed.lane !== null && t.gridL !== null && t.gridN !== null) {
      this.wire(N, [[right, feed.lane + CORE], [t.gridN, feed.lane + CORE], [t.gridN, bottom]]);
      this.wire(INPUT_WIRE, [[right, feed.lane], [t.gridL, feed.lane], [t.gridL, bottom]]);
    }
    const to = byId.get(x.to);
    if (to) {
      const top = this.lay.rows[to.row].top;
      const xl = to.x + to.w - 1.5 * MODULE, xn = to.x + to.w - MODULE / 2;
      this.wire(N, [[t.loadN, bottom], [t.loadN, bottom + 8], [e.x - 14, bottom + 8], [e.x - 14, top + 7],
                    [xn, top + 7], [xn, to.y + SCREW]]);
      this.wire(RESERVE, [[t.loadL, bottom], [t.loadL, bottom + 4], [e.x - 10, bottom + 4], [e.x - 10, top + 3],
                          [xl, top + 3], [xl, to.y + SCREW]]);
      const sw = x.switch && x.switch !== x.to ? byId.get(x.switch) : undefined;
      if (sw) this.outputJumper(to, sw);
    }
    // PE — вдоль правой стенки щита вверх к последней клемме клеммника PE
    const pe = this.lay.pe, last = termX(pe, this.lay.terminals), peY = pe.y + pe.h + 4;
    const trunk = right - PE_TRUNK, y = bottom + 12;
    this.wire(PE, [[t.pe, bottom], [t.pe, y], [trunk, y], [trunk, peY], [last, peY], [last, pe.y + pe.h - 6]],
              PE_STRIPE);
    if (this.lay.dc && this.data.dc && t.glands) this.dcBox(pen, bottom, t.glands);
  }

  // Щит АКБ: корпус и аппараты; от верхних клемм — вверх своими дорожками и влево в вводы
  // инвертора (АКБ — в BAT+ и BAT−, строка панелей — парой в свой ввод PV); от нижних
  // клемм автомата АКБ — кабели к АКБ, строк панелей — вниз и вправо к подписи; УЗИП строки
  // — перемычками к клеммам её автомата, PE — вниз к метке
  private dcBox(pen: Pen, invBottom: number, glands: { bat: [number, number]; pv: number[] }) {
    const dc = this.lay.dc!, data = this.data.dc!;
    const enc = dc.enclosure;
    const used = data.devices.reduce((s, d) => s + d.model.modules, 0);
    // Подпись — под АКБ: над корпусом идут провода к инвертору, под ним — к АКБ и панелям
    text(pen, `${data.texts.title} · ${enc.title} · ${used}/${enc.rows * enc.per_row} DIN`,
         dc.battery.x, dc.battery.y + dc.battery.h + 8, LABEL, pen.ink, "left");
    this.enclosure(pen, dc.box, enc);
    for (const y of dc.rails) this.rail(pen, dc.box.x + 12, dc.box.x + dc.box.w - 12, y);
    for (const p of dc.placed) this.device(pen, p);
    const poles = (p: Placed) => [p.x + MODULE / 2, p.x + p.w - MODULE / 2];  // «+» и «−»
    // Вверх к инвертору: по порядку слева направо — у правого провода дорожка выше
    const ups: { x: number; y: number; to: number; color: string; width: number }[] = [];
    const battery = dc.placed.find((p) => p.dev.kind === "dc_battery");
    const strings = dc.placed.filter((p) => p.dev.kind === "dc_breaker");
    const thick = WIRE * 1.6;
    if (battery) {
      const [xp, xm] = poles(battery);
      ups.push({ x: xp, y: battery.y + SCREW, to: glands.bat[0], color: DC_PLUS, width: thick });
      ups.push({ x: xm, y: battery.y + SCREW, to: glands.bat[1], color: DC_MINUS, width: thick });
    }
    strings.forEach((p, k) => {
      const [xp, xm] = [p.x + MODULE / 2, p.x + 1.5 * MODULE], g = glands.pv[k] ?? glands.pv[0];
      ups.push({ x: xp, y: p.y + SCREW, to: g - 1.5, color: DC_PLUS, width: WIRE });
      ups.push({ x: xm, y: p.y + SCREW, to: g + 1.5, color: DC_MINUS, width: WIRE });
    });
    ups.forEach((u, k) => {
      const lane = dc.lanes[k];
      this.wire(u.color, [[u.x, u.y], [u.x, lane], [u.to, lane], [u.to, invBottom]], undefined, u.width);
    });
    // УЗИП строки — перемычки к клеммам автомата строки, PE — вниз к метке
    for (const f of dc.placed.filter((p) => p.dev.kind === "dc_spd")) {
      const q = strings[dc.placed.filter((p) => p.dev.kind === "dc_spd").indexOf(f)];
      if (q) {
        const y = f.y + SCREW;
        this.wire(DC_MINUS, [[f.x + 1.5 * MODULE, y], [f.x + 1.5 * MODULE, y - 13], [q.x + 1.5 * MODULE, y - 13]], undefined, 1.2);
        this.wire(DC_PLUS, [[f.x + MODULE / 2, y], [f.x + MODULE / 2, y - 16], [q.x + MODULE / 2, y - 16]], undefined, 1.2);
      }
      const cx = f.x + f.w / 2, from = f.y + f.h - SCREW;
      this.wire(PE, [[cx, from], [cx, from + 16]], PE_STRIPE, 1.6);
      text(pen, "PE", cx, from + 21, 4.5, PE);
    }
    // Строки панелей: из нижних клемм вниз под корпус и вправо к подписи
    const end = dc.box.x + dc.box.w + 10;
    strings.forEach((p, k) => {
      const from = p.y + p.h - SCREW;
      const [lp, lm] = [dc.pvLanes[2 * k], dc.pvLanes[2 * k + 1]];
      this.wire(DC_PLUS, [[p.x + MODULE / 2, from], [p.x + MODULE / 2, lp], [end, lp]]);
      this.wire(DC_MINUS, [[p.x + 1.5 * MODULE, from], [p.x + 1.5 * MODULE, lm], [end, lm]]);
      text(pen, `PV${k + 1} · ${data.texts.pv}`, end + 3, (lp + lm) / 2, LABEL, pen.ink, "left");
    });
    if (battery) this.battery(pen, battery, poles(battery), data);
  }

  // АКБ — шкаф с лицевой панелью и индикатором заряда; клеммы «+» и «−» сверху под полюсами
  // автомата АКБ, кабели — к его нижним клеммам
  private battery(pen: Pen, qb: Placed, [xp, xm]: number[], data: NonNullable<PanelData["dc"]>) {
    const { ctx } = pen, r = this.lay.dc!.battery, b = data.battery;
    ctx.fillStyle = "#3b4046"; ctx.strokeStyle = "#22262a"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.roundRect(r.x, r.y, r.w, r.h, 5); ctx.fill(); ctx.stroke();
    ctx.fillStyle = "#4a5057";
    ctx.beginPath(); ctx.roundRect(r.x + 8, r.y + 14, r.w - 16, r.h * 0.42, 3); ctx.fill();
    // Индикатор заряда
    const dx = r.x + 18, dy = r.y + 24, dw = r.w - 36, dh = 16;
    ctx.fillStyle = "#9fd6c8";
    ctx.beginPath(); ctx.roundRect(dx, dy, dw, dh, 2); ctx.fill();
    text(pen, `${b.voltage} V  ▮▮▮▮▯`, dx + dw / 2, dy + dh / 2, 7, "#173b33");
    const v = `${b.voltage} В${b.voltage_assumed ? "*" : ""}`;
    const kwh = data.texts.kwh ?? "кВт·год";  // старый .epd — без единицы на языке проекта
    const cap = b.capacity ? ` · ${String(b.capacity).replace(".", ",")} ${kwh}` : "";
    text(pen, `${data.texts.battery} ${v}${cap}`, r.x + r.w / 2, r.y + r.h * 0.42 + 2, 6.5, "#e8e8e6");
    // Рёбра на нижней части
    ctx.strokeStyle = "#2d3136"; ctx.lineWidth = 1;
    for (let y = r.y + r.h * 0.62; y < r.y + r.h - 8; y += 9) {
      ctx.beginPath(); ctx.moveTo(r.x + 10, y); ctx.lineTo(r.x + r.w - 10, y); ctx.stroke();
    }
    // Клеммы и кабели к автомату АКБ
    const from = qb.y + qb.h - SCREW, thick = WIRE * 1.6;
    for (const [x, color, sign] of [[xp, DC_PLUS, "+"], [xm, DC_MINUS, "−"]] as const) {
      ctx.fillStyle = color;
      ctx.beginPath(); ctx.roundRect(x - 5, r.y - 6, 10, 7, 1.5); ctx.fill();
      text(pen, sign, x, r.y - 2.6, 6, "#ffffff");
      this.wire(color, [[x, r.y - 6], [x, from]], undefined, thick);
    }
    const box = this.lay.dc!.box;
    // Слева от кабелей АКБ: справа идут провода строк панелей
    text(pen, `2×${String(b.cable).replace(".", ",")} мм² · ${b.rating} А`, xp - 7, (box.y + box.h + r.y) / 2,
         5.5, pen.ink, "right");
  }

  // Автомат выхода инвертора → вход II АВР или переключателя: с нижних клемм под рейкой
  // влево в два последних модуля переключателя снизу; L (левый полюс) — выше и в крайний
  // модуль, N — ниже и в соседний: перемычки не пересекаются
  private outputJumper(out: Placed, sw: Placed) {
    const y = this.lay.rows[out.row].gutterTop, from = out.y + out.h - SCREW;
    const l = out.x + MODULE / 2, n = out.x + 1.5 * MODULE;
    const tl = sw.x + sw.w - MODULE / 2, tn = sw.x + sw.w - 1.5 * MODULE, into = sw.y + sw.h - SCREW;
    this.wire(N, [[n, from], [n, y + 6.5], [tn, y + 6.5], [tn, into]]);
    this.wire(RESERVE, [[l, from], [l, y + 3], [tl, y + 3], [tl, into]]);
  }

  // Гибридный инвертор (вид как у настенных на 5 кВт): светлый корпус с рёбрами радиатора по
  // бокам, тёмная лицевая панель с дисплеем, индикаторами и кнопками, внизу — вводы АКБ и
  // PV (сальники) и клеммы LOAD, GRID, PE. Вилка генератора — тот же корпус без GRID.
  // Возвращает x клемм
  private inverterBody(pen: Pen, e: Rect, x: NonNullable<PanelData["external"]>) {
    const { ctx } = pen, w = e.w, h = e.h;
    const inverter = x.kind === "inverter";
    text(pen, `${x.id} · ${x.title}`, e.x, e.y - 5, LABEL, pen.ink, "left");
    // Корпус и рёбра радиатора
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
    // Лицевая панель
    const px = e.x + w * 0.14, pw = w * 0.72, py = e.y + h * 0.1, ph = h * 0.36;
    ctx.fillStyle = "#2a2d31";
    ctx.beginPath(); ctx.roundRect(px, py, pw, ph, 5); ctx.fill();
    // Дисплей
    const dx = px + pw * 0.1, dw = pw * 0.8, dy = py + ph * 0.1, dh = ph * 0.36;
    ctx.fillStyle = "#9fd6c8";
    ctx.beginPath(); ctx.roundRect(dx, dy, dw, dh, 2); ctx.fill();
    const fs = dh * 0.28;
    text(pen, inverter ? "230V  50Hz" : "GEN 230V", dx + dw / 2, dy + dh * 0.32, fs, "#173b33");
    text(pen, inverter ? "5.0 kW  ▮▮▮▯ 76%" : "STANDBY", dx + dw / 2, dy + dh * 0.7, fs * 0.9, "#173b33");
    // Индикаторы: DC, AC, норма, авария
    const leds = ["#3ecf5a", "#3ecf5a", "#3ecf5a", "#5a2a2a"];
    leds.forEach((c, k) => {
      const lx = dx + dw * (0.12 + k * 0.25), ly = dy + dh + ph * 0.12;
      ctx.fillStyle = c;
      ctx.beginPath(); ctx.arc(lx, ly, Math.max(1.6, ph * 0.035), 0, 2 * Math.PI); ctx.fill();
    });
    // Кнопки
    for (let k = 0; k < 4; k++) {
      const bx = dx + dw * (0.12 + k * 0.25), by = dy + dh + ph * 0.32;
      ctx.fillStyle = "#4a4f55";
      ctx.beginPath(); ctx.roundRect(bx - pw * 0.06, by - ph * 0.05, pw * 0.12, ph * 0.1, 1.5); ctx.fill();
    }
    text(pen, inverter ? "HYBRID INVERTER" : "POWER INLET", e.x + w / 2, py + ph + h * 0.05, h * 0.022, "#7a7d80");
    // Нижняя панель подключений
    const cy = e.y + h * 0.84, ch = h * 0.13;
    ctx.fillStyle = "#3a3d42";
    ctx.beginPath(); ctx.roundRect(e.x + w * 0.04, cy, w * 0.92, ch, 3); ctx.fill();
    // Вводы АКБ и PV справа — к щиту АКБ (он правее), клеммы сети слева — к щиту
    const glands = inverter ? ["BAT+", "BAT−", "PV1", "PV2"] : [];
    const gxs = glands.map((_, k) => e.x + w * (0.6 + k * 0.085 + (k >= 2 ? 0.04 : 0)));
    glands.forEach((g, k) => {
      const gx = gxs[k], gy = cy + ch * 0.45;
      ctx.fillStyle = "#16181b";
      ctx.beginPath(); ctx.arc(gx, gy, w * 0.026, 0, 2 * Math.PI); ctx.fill();
      text(pen, g, gx, cy + ch * 0.85, ch * 0.13, "#c9ccd0");
    });
    // Клеммы: LOAD L N, GRID L N, PE
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
}

// Тёмный цвет — подпись на нём белая
function dark(hex: string): boolean {
  const n = parseInt(hex.replace("#", "").slice(0, 6), 16);
  return 0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255) < 150;
}

