// Panel front view in its own canvas, drawn from the panel data (page key panel), not from sheet
// primitives: scale and pan here, the drawing itself in painter.ts. Objects under the cursor are
// not looked up: highlighting comes only from a side panel table row (store.lit) and an open card
// (store.pinned, a click on a device or row): the device and the group wire glow. Hovered items
// use --hl, the glow fades in and pulses gently (steady without animation); pinned by click uses
// its own --pin colour, steady, no pulse: hovering other rows leaves it alone.

import { Pinch } from "@/engine/sheet/pinch";
import { FIT_SHRINK, REDUCED_MOTION, VIEW_PAD } from "@/shared/consts";
import { palette, refreshPalette, screenColor } from "@/shared/palette";
import { view } from "@/shared/store";
import type { PanelData } from "@/shared/types";
import { clampStep, Glide, LAST_STEP, PinchSteps, RAIL_PX, WheelSteps, type Zoom, ZOOM_STEPS, zoomLabel } from "@/shared/zoom";
import type { Pen } from "./catalog";
import { groupPath, LABEL_STEP, LABELS, layout, type PanelLayout, type Placed } from "./layout";
import { PanelPainter, TITLE, tracePath, WIRE } from "./painter";

const GLOW_IN = 180;       // ms: glow fade-in
const GLOW_PERIOD = 1400;  // ms: pulse period

export class PanelView {
  onZoom: (zoom: Zoom) => void = () => {};
  private ctx: CanvasRenderingContext2D;
  private step = 0;  // zoom step (zoom.ts)
  private readonly wheel = new WheelSteps();
  private readonly pinchSteps = new PinchSteps();
  private readonly glide = new Glide();
  private lay: PanelLayout;
  private w = 1; private h = 1; private dpr = 1;
  private scale = 1; private fitScale = 1; private ox = 0; private oy = 0;
  private drag: { x: number; y: number; ox: number; oy: number } | null = null;
  private readonly font: string;
  private readonly painter: PanelPainter;
  private readonly cleanup: (() => void)[] = [];
  private litAt = 0; private pinAt = 0; private pulse = 0;
  private down: { x: number; y: number } | null = null;
  private readonly pinch = new Pinch();

  constructor(private readonly canvas: HTMLCanvasElement, private readonly wrap: HTMLElement,
              data: PanelData, language?: string) {
    this.ctx = canvas.getContext("2d")!;
    this.font = getComputedStyle(document.body).fontFamily || "sans-serif";
    this.lay = layout(data);
    this.painter = new PanelPainter(this.ctx, this.lay, data, language);
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

  // Hovered: the table row under the cursor, except the pinned one, which glows in its own colour
  private hoverKeys(): Set<string> {
    const { lit, pinned } = view.get();
    const out = new Set(lit || []);
    if (pinned) out.delete(pinned);
    return out;
  }

  // Devices of the panel, the battery box and the LED box, for clicks and highlighting
  private allPlaced(): Placed[] {
    return [...this.lay.placed, ...(this.lay.dc?.placed || []), ...(this.lay.led?.placed || [])];
  }

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
    const l = this.lay, top = -TITLE * 2;  // heading above the input
    this.scale = FIT_SHRINK * Math.min((this.w - RAIL_PX - 2 * VIEW_PAD) / l.width, (this.h - 2 * VIEW_PAD) / (l.height - top));
    this.fitScale = this.scale;
    this.step = 0;
    this.ox = (this.w - RAIL_PX - l.width * this.scale) / 2;
    this.oy = (this.h - (l.height + top) * this.scale) / 2;
    this.draw();
  }

  // Neighbouring zoom step at screen point (x, y); none past the ends
  zoomStep(dir: number, x = (this.w - RAIL_PX) / 2, y = this.h / 2) { this.zoomTo(this.step + dir, x, y); }

  // Zoom step, smoothly, keeping screen point (x, y) in place
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
      if (this.pinch.down(ev)) { this.drag = null; this.down = null; return; }  // a pinch, not a pan
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
    // Click (without a drag): the card of the device under the cursor; off the devices, close it
    this.on("pointerup", (ev) => {
      this.pinch.up(ev);
      const d = this.pinch.used ? null : this.down;  // end of a pinch is not a click
      this.down = null;
      end();
      if (!d || Math.hypot(ev.clientX - d.x, ev.clientY - d.y) > 4) return;
      const r = this.canvas.getBoundingClientRect();
      const mx = (ev.clientX - r.left - this.ox) / this.scale, my = (ev.clientY - r.top - this.oy) / this.scale;
      const hit = this.allPlaced().find((p) => mx >= p.x && mx <= p.x + p.w && my >= p.y && my <= p.y + p.h);
      view.set({ pinned: hit ? hit.dev.key : null });
    });
    this.on("pointercancel", (ev) => { this.pinch.up(ev); end(); });
    // Double click zooms one step in at the click point; at the last step, fit the whole panel
    this.on("dblclick", (ev) => {
      const r = this.canvas.getBoundingClientRect();
      if (this.step >= LAST_STEP) this.fit(); else this.zoomStep(1, ev.clientX - r.left, ev.clientY - r.top);
    });
  }

  draw() {
    refreshPalette();
    const { ctx } = this;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.fillStyle = palette.paper || "#ffffff";
    ctx.fillRect(0, 0, this.w, this.h);
    ctx.setTransform(this.dpr * this.scale, 0, 0, this.dpr * this.scale, this.dpr * this.ox, this.dpr * this.oy);
    const pen = { ctx, font: this.font, ink: screenColor("#2b2b2b") };
    this.painter.paint(pen);
    this.highlight(pen);
    // Highlight glow: the next frame while hovered (pulse) or while the pinned one fades in
    const fading = !!view.get().pinned && performance.now() - this.pinAt < GLOW_IN;
    if ((this.hoverKeys().size || fading) && !REDUCED_MOTION && !this.pulse) {
      this.pulse = requestAnimationFrame(() => { this.pulse = 0; this.draw(); });
    }
    this.onZoom({ step: this.step, label: zoomLabel(this.step), pxPerMm: this.scale });
  }

  // Highlight: a pinned device is steady in --pin; one hovered via a table row uses --hl, fading
  // in over GLOW_IN, then pulsing gently. The device and its group wire glow, the label row gets
  // a soft background
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

  // Glow of one device: group wire on top, fill with a halo, label row background; wave is
  // 0…1, how much the halo and fill "breathe" (constant for a pinned one)
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
      tracePath(ctx, groupPath(this.lay, p));
      ctx.stroke();
    }
    // The device: translucent fill with a halo
    ctx.fillStyle = color;
    ctx.globalAlpha = fade * (0.05 + 0.04 * wave);  // translucent: the device stays visible
    ctx.beginPath(); ctx.roundRect(p.x, p.y, p.w, p.h, 2); ctx.fill();
    ctx.shadowBlur = 0;
    if (p.label !== null) {
      ctx.globalAlpha = fade * 0.14;
      ctx.beginPath(); ctx.roundRect(this.lay.labelX - 2, p.label - LABEL_STEP / 2, LABELS, LABEL_STEP, 2); ctx.fill();
    }
    ctx.restore();
  }
}
