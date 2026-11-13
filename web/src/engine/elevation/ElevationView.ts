// Wall elevation in its own canvas: drawn from the elevation data (page key elevations), not
// from sheet primitives: it behaves differently, without the layers and highlighting of the
// combined drawing. The wall is in mm (x from the left corner, view from inside; y from the
// floor), labels in screen px: point numbers as badges in the group colour (like the wiring
// lines), offsets at the bottom, heights on the right.
// Under the cursor: a point, box or panel (store.hover); a click pins it (store.pinned);
// highlighted is the same as the "On the wall" row in the side panel (store.lit).
// Isometry (mode "iso", iso.ts): the wall at 45° and part of the neighbouring one at the
// corner: the same flat wall drawing (badges, dashes, labelled scales) through its plane
// matrix, so labels and dimensions are isometric too; the neighbour is translucent, without
// scales, its cut edge drawn as a wave.
// Hovered and pinned items go on top of everything else (badges and symbols are drawn last).

import { Pinch } from "@/engine/sheet/pinch";
import { FIT_SHRINK } from "@/shared/consts";
import { gridStep, paintGrid } from "@/engine/sheet/grid";
import { palette, refreshPalette, screenColor } from "@/shared/palette";
import { view } from "@/shared/store";
import type { ElevWall, Elevation, PipeKind, XY } from "@/shared/types";
import { clampStep, Glide, LAST_STEP, PinchSteps, RAIL_PX, WheelSteps, type Zoom, ZOOM_STEPS, zoomLabel } from "@/shared/zoom";
import { apply, flatToIso, invert, isoBounds, isoScene, wallOutline, type Affine, type IsoScene, type Mat } from "./iso";
import { badgePlaces, handleSpan, HANDLE, leader, spread, type Rect } from "./layout";

const PAD = 20;            // px around the elevation
const RULER_X = 64;        // px below the floor: offsets
const RULER_Y = 58;        // px on the right: heights
const HEAD = 8;            // px above the ceiling
const PAGER = 52;          // px on top: wall pager (Viewer) above the elevation
const MAP = { w: 264, h: 250 };  // mini map at the bottom left (WallMap, 240 px plus margins): room for it
const LABEL_PX = 11;       // dimension labels
const BADGE_PX = 12;       // point number
const SYMBOL_MM = 34;      // Ø68 flush box radius
const PITCH_MM = 71;       // post step in a frame
const FIXING_MM = 40;      // half the fixing stroke across a cable drop
const CABLE_PITCH_MM = 15;  // cables of one drop side by side, wall mm
const CABLE_OUT = 8;       // px: a cable from the ceiling or floor goes on past the wall edge
const CABLE_W = 0.6;       // px: cable line width
const FIXING_ALPHA = 0.5;  // fixings are half transparent: the cables show through them
const CABLE_ROOM = 3;      // px either side of a cable that labels keep off
const LEADER = "#9a9288";   // dashed leader from a moved label to its anchor
const MIN_R = 5;           // px: symbol no smaller than this
const ISO_PAD = 28;        // px around the isometry: number badges
const SIDE_ALPHA = 0.45;   // neighbouring wall in isometry is translucent
const SWITCHES = new Set(["switch", "pass_switch"]);
const LOW = new Set(["data", "tv"]);

const INK = "#29251f", GREY = "#9a9288", LIGHT = "#d9d3c8", BACK = "#b0a99d";
const GLASS = "#a9d3f2";
const CHASE = "#e4ded3", CHASE_LOW = "#cfe3f3", BOX = "#b3261e", LOW_INK = "#1f6fb2";
// Plumbing: network colours, as on the "Plumbing" sheet (drawing/plumbing.COLORS)
export const WATER: Record<PipeKind, string> = { cold: "#1f77b4", hot: "#d62728", sewer: "#8c564b" };

interface Hit { key: string; r: Rect; inv: Affine | null }  // inv: screen → flat wall view

export type ElevMode = "flat" | "iso";

// A cable's turn past an opening, flat view px (ElevationView.turns)
interface Turn {
  cx: number; cy: number; r: number; kx: number; ky: number;
  group: string; label: string | null; ox: number; oy: number;
}

// How to draw a wall: visible part from…to (mm), outline (mm; the neighbour has the wavy cut)
// and whether to clip by it, dimension scales and which side heights go on (null means no
// scales), outlets from the far side, fill
interface WallOpts {
  from: number; to: number; outline: XY[] | null; clip: boolean;
  rulers: "right" | "left" | null; back: boolean; alpha: number; shade: number;
}

export class ElevationView {
  onZoom: (zoom: Zoom) => void = () => {};
  private ctx: CanvasRenderingContext2D;
  private step = 0;  // zoom step (zoom.ts)
  private readonly wheel = new WheelSteps();
  private readonly pinchSteps = new PinchSteps();
  private readonly glide = new Glide();
  private w = 1; private h = 1; private dpr = 1;
  private scale = 1; private fitScale = 1; private ox = 0; private oy = 0;  // screen = o + mm·scale (y up)
  private drag: { x: number; y: number; ox: number; oy: number } | null = null;
  private down: { x: number; y: number } | null = null;
  private hits: Hit[] = [];
  private iso: IsoScene | null = null;  // isometry; null means a flat elevation
  private inv: Affine | null = null;    // while the isometry wall is drawn: screen → its flat view
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
      const now = [s.hover, s.lit, s.pinned, s.themeTick, s.wallLayers];
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

  // The whole wall with labels; room for the mini map on the left or at the bottom, whichever makes the elevation larger
  fit() {
    const d = this.data;
    this.glide.stop();
    // Frame in screen mm and label margins in px: a flat view has scales at the bottom and right
    const [X0, Y0, X1, Y1] = this.iso ? isoBounds(this.iso) : [0, 0, d.length, d.top];
    // Isometry: offsets under the floor, heights at the wall edge far from the corner
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

  // Neighbouring zoom step at screen point (x, y); none past the ends
  zoomStep(dir: number, x = this.cx(), y = this.h / 2) { this.zoomTo(this.step + dir, x, y); }

  // Zoom step, smoothly, keeping screen point (x, y) in place
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
    // On top is what was drawn later (points over boxes)
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
    // A click without a drag pins the object (the panel row) or unpins it
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
    // Double click zooms one step in at the click point; at the last step, fit the whole wall
    this.on("dblclick", (ev) => {
      const r = this.canvas.getBoundingClientRect();
      if (this.step >= LAST_STEP) this.fit(); else this.zoomStep(1, ev.clientX - r.left, ev.clientY - r.top);
    });
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
    // The grid of the sheet (sheet/grid.ts) in wall mm; the wall itself stays plain paper
    paintGrid(ctx, this.dpr * this.ox, this.dpr * this.oy, gridStep(this.dpr * this.scale) * this.dpr * this.scale);
    this.hits = [];
    const d = this.data;
    if (!this.iso) ctx.fillRect(this.sx(0), this.sy(d.height), d.length * this.scale, d.height * this.scale);
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

  // Turns past an opening in flat view px, by `${key}@${x}`: arc centre, radius, the lane corner,
  // and per bundle (group) the outer corner and the radius label
  private turns(cables: NonNullable<ElevWall["cables"]>, lanes: Map<string, number>) {
    const out = new Map<string, Turn>();
    const verticals = new Map(cables.filter((c) => c.x1 === undefined).map((c) => [`${c.key}@${c.x}`, c]));
    const corners = new Map<string, { x: number; y: number; vx: number; vy: number; cs: typeof cables }>();
    for (const c of cables) {
      const v = verticals.get(`${c.key}@${c.x}`);
      if (c.x1 === undefined || !v) continue;
      const up = v.y1 > c.y0 + 0.5, vx = c.x1 > c.x ? 1 : -1, vy = up ? -1 : 1;  // screen y down
      const id = `${c.x}|${c.y0}|${vx}|${vy}`;
      const g = corners.get(id) ?? { x: c.x, y: c.y0, vx, vy, cs: [] };
      g.cs.push(c); corners.set(id, g);
    }
    for (const [id, { x, y, vx, vy, cs }] of corners) {
      const lane = (c: (typeof cs)[number]) => lanes.get(`${c.key}@${x}`) ?? 0;
      const inner = cs.reduce((a, c) => (lane(c) * vx > lane(a) * vx ? c : a));
      const X = this.sx(x), Y = this.sy(y), ix = X + lane(inner), iy = Y + lane(inner) * vx * vy;
      const reach = Math.min(...cs.map((c) => Math.abs(this.sx(c.x1!) - ix)));
      const rise = Math.min(...cs.map((c) => { const v = verticals.get(`${c.key}@${x}`)!; return Math.abs(this.sy(vy < 0 ? v.y1 : v.y0) - iy); }));
      const r0 = Math.min((inner.r ?? 0) * this.scale, reach, rise);
      const cx = ix + vx * r0, cy = iy + vy * r0;
      const radii = cs.map((c) => c.r).filter((r): r is number => r !== undefined).sort((a, b) => a - b);
      const lo = radii.length ? Math.round(radii[0]) : null, hi = radii.length ? Math.round(radii[radii.length - 1]) : null;
      const label = lo === null ? null : lo === hi ? `R${lo}` : `R${lo}–${hi}`;
      const outer = cs.reduce((a, c) => (lane(c) * vx < lane(a) * vx ? c : a));
      const ot = (lane(inner) - lane(outer)) * vx, ox = X + lane(outer), oy = iy - vy * ot;
      for (const c of cs) {
        const t = (lane(inner) - lane(c)) * vx;
        out.set(`${c.key}@${x}`, { cx, cy, r: r0 + t, kx: X + lane(c), ky: iy - vy * t, group: id, label, ox, oy });
      }
    }
    return out;
  }

  private hit(key: string, r: Rect) { this.hits.push({ key, r, inv: this.inv }); }

  // The wall in flat view px (in isometry, under the plane matrix): chases, edges, openings,
  // panel, dashes to the scales, boxes, points, scales, numbers. Highlighted items last, on top
  private paintWall(e: ElevWall, lit: Set<string>, o: WallOpts) {
    const { ctx } = this, d = this.data, s = this.scale;
    const x0 = this.sx(o.from), x1 = this.sx(o.to), floor = this.sy(0), ceil = this.sy(d.height), top = this.sy(d.top);
    const r = Math.max(SYMBOL_MM * s, MIN_R), pitch = Math.max(PITCH_MM * s, 2 * r + 1);
    const seen = (x: number) => x >= o.from - 1 && x <= o.to + 1;
    const edge = o.rulers === "left" ? x0 : x1;  // the edge with the height scale
    const taken: Rect[] = [];
    const layers = view.get().wallLayers;
    const elec = layers.electrical;
    const points = elec ? e.points.filter((p) => seen(p.x)) : [];
    const boxes = elec ? e.boxes.filter((b) => seen(b.x)) : [];
    const board = elec && e.board && seen(e.board.x) ? e.board : null;
    const last = <T extends { key: string }>(xs: T[]) => [...xs.filter((x) => !lit.has(x.key)), ...xs.filter((x) => lit.has(x.key))];

    ctx.save();
    ctx.globalAlpha = o.alpha;
    // Wall outline: fill and clip (the neighbour gets a wavy cut)
    if (o.outline) {
      ctx.beginPath();
      o.outline.forEach(([x, y], i) => (i ? ctx.lineTo(this.sx(x), this.sy(y)) : ctx.moveTo(this.sx(x), this.sy(y))));
      ctx.closePath();
      ctx.fillStyle = palette.paper || "#ffffff"; ctx.globalAlpha = 1; ctx.fill(); ctx.globalAlpha = o.alpha;  // no grid through a wall
      if (o.shade) { ctx.fillStyle = screenColor(INK); ctx.globalAlpha = o.alpha * o.shade; ctx.fill(); ctx.globalAlpha = o.alpha; }
      ctx.save();
      ctx.strokeStyle = screenColor(INK); ctx.lineWidth = 1.4; ctx.stroke();
      ctx.restore();
      if (o.clip) ctx.clip();
    }

    // Chases under everything
    for (const c of elec ? e.chases : []) {
      const half = Math.max(((c.wide ? 50 : 30) / 2) * s, 1.5);
      ctx.fillStyle = screenColor(c.low ? CHASE_LOW : CHASE);
      if (c.x1 !== undefined) {  // the turn past an opening, along the wall
        const a = Math.min(this.sx(c.x), this.sx(c.x1)), b = Math.max(this.sx(c.x), this.sx(c.x1));
        ctx.fillRect(a - half, this.sy(c.y0) - half, b - a + 2 * half, 2 * half);
        continue;
      }
      ctx.fillRect(this.sx(c.x) - half, this.sy(c.y1), 2 * half, (c.y1 - c.y0) * s);
    }
    // Cables along the wall, those of one drop side by side in their group colour; a fixing is
    // one line across the cables of its drop, their number "×5" at the top one (the clips snap
    // together: decision 2026-11-12)
    const lane = Math.max(CABLE_PITCH_MM * s, 3);
    const drops = new Map<number, number>();
    const cables = elec ? e.cables ?? [] : [];
    for (const c of cables) if (c.x1 === undefined) drops.set(c.x, (drops.get(c.x) ?? 0) + 1);
    const placed = new Map<number, number>();
    // The turn past an opening: from the foot of its drop along the wall to the point
    const lanes = new Map<string, number>();
    for (const c of cables) {
      if (c.x1 !== undefined) continue;
      const n = drops.get(c.x)!, k = placed.get(c.x) ?? 0;
      placed.set(c.x, k + 1);
      lanes.set(`${c.key}@${c.x}`, (k - (n - 1) / 2) * lane);
    }
    // A turn past an opening is an arc of its bend radius round one centre for the bundle: the
    // inner lane (nearest the side it turns to) at its radius, each outer one a lane further;
    // the radius never takes more than the arms have. "R130–160" outside the corner
    const turns = this.turns(cables, lanes);
    placed.clear();
    for (const c of cables) {
      const turn = turns.get(`${c.key}@${c.x}`);
      if (c.x1 !== undefined) {
        if (!turn) continue;
        const { cx, cy, kx, ky, r: rr } = turn;
        ctx.save();
        ctx.strokeStyle = screenColor(c.color ?? INK); ctx.lineWidth = CABLE_W;
        ctx.beginPath(); ctx.moveTo(kx, cy); ctx.arcTo(kx, ky, cx, ky, Math.max(rr, 0.01)); ctx.lineTo(this.sx(c.x1), ky); ctx.stroke();
        ctx.restore();
        const ex = this.sx(c.x1);
        taken.push([Math.min(kx, cx) - CABLE_ROOM, Math.min(cy, ky) - CABLE_ROOM, Math.max(kx, cx) + CABLE_ROOM, Math.max(cy, ky) + CABLE_ROOM]);
        taken.push([Math.min(cx, ex), ky - CABLE_ROOM, Math.max(cx, ex), ky + CABLE_ROOM]);
        continue;
      }
      const n = drops.get(c.x)!, k = placed.get(c.x) ?? 0;
      placed.set(c.x, k + 1);
      const x = this.sx(c.x) + (k - (n - 1) / 2) * lane;
      // The end on the route plane goes on past the wall: the cable runs on in the floor or
      // ceiling; the end at a turn stops where its arc starts
      let lo = this.sy(c.y0) + (c.y0 <= 0.5 ? CABLE_OUT : 0);
      let hi = this.sy(c.y1) - (c.y1 >= d.height - 0.5 ? CABLE_OUT : 0);
      if (turn) { if (turn.cy < turn.ky) lo = turn.cy; else hi = turn.cy; }
      this.line(x, lo, x, hi, c.color ?? INK, CABLE_W);
      taken.push([x - CABLE_ROOM, Math.min(lo, hi), x + CABLE_ROOM, Math.max(lo, hi)]);
    }
    // Plain labels (fixing counts, turn radii) go after the numbers, where there is room
    const notes: { key: string; text: string; anchor: Rect }[] = [];
    for (const b of new Map([...turns.values()].map((t) => [t.group, t])).values()) {
      if (!b.label) continue;
      // Anchor: the middle of the outer lane's arc
      const k = Math.abs(b.cx - b.ox) * Math.SQRT1_2, mx = b.cx - Math.sign(b.cx - b.ox) * k, my = b.cy - Math.sign(b.cy - b.oy) * k;
      notes.push({ key: `bend:${b.group}`, text: b.label, anchor: [mx - 1, my - 1, mx + 1, my + 1] });
    }
    const fixings = elec ? e.fixings ?? [] : [];
    const tops = new Map<number, number>();
    for (const f of fixings) tops.set(f.x, Math.max(tops.get(f.x) ?? -Infinity, f.y));
    for (const f of fixings) {
      const spread = (Math.max(f.n ?? 1, drops.get(f.x) ?? 1) - 1) / 2 * lane;
      const half = Math.max(FIXING_MM * s, 3) + spread, x = this.sx(f.x), y = this.sy(f.y);
      ctx.save(); ctx.globalAlpha *= FIXING_ALPHA;
      this.line(x - half, y, x + half, y, INK, 1.2);
      ctx.restore();
      if ((f.n ?? 1) > 1 && f.y === tops.get(f.x)) notes.push({ key: `fix:${f.x}`, text: `×${f.n}`, anchor: [x - half, y - 1, x + half, y + 1] });
    }

    // Wall: floor and ceiling lines thicker, ends are the room corners
    this.line(x0, floor, x1, floor, INK, 2.5);
    this.line(x0, ceil, x1, ceil, INK, 2.5);
    if (!o.outline) {
      this.line(x0, top, x0, floor, INK, 1.4);
      this.line(x1, top, x1, floor, INK, 1.4);
    }

    for (const op of e.openings) {
      const a = this.sx(op.x0), b = this.sx(op.x1), y0 = this.sy(op.y0), y1 = this.sy(op.y1);
      const color = op.assumed ? GREY : INK;
      ctx.fillStyle = op.kind === "window" ? GLASS : palette.paper || "#ffffff";
      ctx.fillRect(a, y1, b - a, y0 - y1);
      ctx.strokeStyle = screenColor(color); ctx.lineWidth = 1.4;
      ctx.strokeRect(a, y1, b - a, y0 - y1);
      if (op.kind === "window") this.line((a + b) / 2, y0, (a + b) / 2, y1, color);
      if (op.kind === "door") {
        this.line(a, y0, (a + b) / 2, y1, LIGHT);
        this.line(b, y0, (a + b) / 2, y1, LIGHT);
        if (op.hinge) {
          const [from, to] = handleSpan(op.x0, op.x1, op.hinge), y = this.sy(HANDLE.height);
          this.line(this.sx(from), y, this.sx(to), y, INK, 3);
          ctx.fillStyle = screenColor(INK);
          ctx.beginPath(); ctx.arc(this.sx(from), y, 3, 0, 2 * Math.PI); ctx.fill();
        }
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

    // Outlets on the far side: faint, without dimensions
    if (o.back && elec) for (const p of d.back) this.symbol(p.type, p.posts, this.sx(p.x) + (p.slot ?? 0) * pitch, this.sy(p.y), r, pitch, BACK, 1, false);

    // Dashes from points to the scales, under the symbols
    if (o.rulers) {
      for (const p of last(points)) {
        // From the middle of the block: the offset in the model is to it
        const cx = this.sx(p.x), cy = this.sy(p.y), half = r + (pitch * ((p.block ?? p.posts) - 1)) / 2;
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

    // Points: each frame post gets its own symbol; the outline is the group colour, thicker when highlighted.
    // Points at one spot are side by side in one frame (slot: shift from the block centre in posts)
    const blocks = new Map<string, Rect>();
    for (const p of last(points)) {
      const cx = this.sx(p.x) + (p.slot ?? 0) * pitch, cy = this.sy(p.y), half = r + (pitch * (p.posts - 1)) / 2;
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

    // Plumbing: pipe rise from the floor in the network colour, a water outlet is a filled circle,
    // a drain a ring of its diameter; fixture number ("Plumbing" sheet) as a badge at the top supply
    const water = layers.water ? (e.water ?? []).filter((v) => seen(v.x)) : [];
    const fixtures = new Map<string, { key: string; n: number; assumed: boolean; rect: Rect }>();
    for (const v of water) {
      const cx = this.sx(v.x), cy = this.sy(v.y);
      const on = lit.has(v.key);
      const color = on ? palette.hl : WATER[v.kind];
      const rr = v.kind === "sewer" ? Math.max((v.d / 2) * s, 4) : Math.max(15 * s, 3);
      this.line(cx, floor, cx, cy + rr, color, on ? 2.4 : 1.6);
      if (o.rulers) this.line(o.rulers === "left" ? cx - rr : cx + rr, cy, edge, cy, on ? palette.hl : GREY, 0.8, [3, 3]);
      ctx.beginPath(); ctx.arc(cx, cy, rr, 0, 2 * Math.PI);
      if (v.kind === "sewer") { ctx.strokeStyle = screenColor(color); ctx.lineWidth = on ? 3 : 2; ctx.stroke(); }
      else { ctx.fillStyle = screenColor(color); ctx.fill(); }
      const rect: Rect = [cx - rr, cy - rr, cx + rr, cy + rr];
      taken.push(rect);
      this.hit(v.key, rect);
      const was = fixtures.get(v.fixture);
      if (!was || rect[1] < was.rect[1]) fixtures.set(v.fixture, { key: v.key, n: v.n, assumed: v.assumed || !!was?.assumed, rect });
      else if (v.assumed) was.assumed = true;
    }

    // Scales before numbers: their space is taken
    if (o.rulers) {
      const shown = { ...e, points, boxes, board: board ?? undefined, water };
      taken.push(this.ordinatesX(shown, floor, x0, x1), this.ordinatesY(shown, edge, floor, top, o.rulers === "left" ? -1 : 1));
    }

    // Numbers: a badge in the group colour next to the symbol where there is room (spots in model
    // order so they do not jump); highlighted ones are drawn last, over those that covered them
    ctx.font = `600 ${BADGE_PX}px ${this.font}`;
    const labels = [
      ...points.map((p) => ({ key: p.key, text: String(p.n), color: p.color || INK, box: false, anchor: blocks.get(p.key)! })),
      ...boxes.map((b) => ({ key: b.key, text: b.label, color: BOX, box: true, anchor: boxRects.get(b.key)! })),
      ...[...fixtures.values()].map((f) => ({ key: f.key, text: `${f.n}${f.assumed ? "*" : ""}`, color: WATER.sewer, box: false, anchor: f.rect })),
    ].map((l) => ({ ...l, w: ctx.measureText(l.text).width + 10 }));
    const places = badgePlaces(labels, BADGE_PX + 6, taken);
    ctx.font = `${LABEL_PX}px ${this.font}`;
    const plain = notes.map((n) => ({ ...n, w: ctx.measureText(n.text).width + 2 }));
    badgePlaces(plain, LABEL_PX + 2, taken, [x0, top, x1, floor]).forEach((p, k) => {
      if (p.far) this.line(...leader(p.at, plain[k].anchor), LEADER, 0.8, [3, 3]);
      this.text(plain[k].text, p.at[0] + 1, (p.at[1] + p.at[3]) / 2, LABEL_PX, INK, "left");
    });
    for (const l of last(labels.map((l, k) => ({ ...l, at: places[k].at, far: places[k].far })))) {
      const on = lit.has(l.key);
      if (l.far) this.line(...leader(l.at, l.anchor), LEADER, 0.8, [3, 3]);
      if (l.box) this.text(l.text, (l.at[0] + l.at[2]) / 2, (l.at[1] + l.at[3]) / 2, BADGE_PX, on ? palette.hl : BOX, "center");
      else this.badge(l.text, l.at, on ? palette.hl : l.color, on);
      this.hit(l.key, l.at);
    }
    // Numbers of the far side's outlets: faint, after our own
    if (o.back && elec) {
      for (const p of d.back) {
        const cx = this.sx(p.x) + r + (pitch * ((p.block ?? p.posts) - 1)) / 2 + 3;
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

  // The flat wall drawing on its plane in isometry (and hit tests through the inverse)
  private onWall(m: Mat, draw: () => void) {
    const { ctx } = this, t = flatToIso(m, this.scale, this.ox, this.oy);
    ctx.save();
    ctx.transform(...t);
    this.inv = invert(t);
    draw();
    this.inv = null;
    ctx.restore();
  }

  // Isometry: floor by the walls, the neighbour at the corner (translucent, no scales, wavy
  // cut), the elevation wall with scales at the edge far from the corner
  private paintIso(iso: IsoScene, lit: Set<string>) {
    const { ctx } = this, d = this.data;
    ctx.beginPath();
    iso.floor.map(this.toScreen).forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.closePath();
    ctx.fillStyle = palette.paper || "#ffffff"; ctx.fill();  // no grid through the floor
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

  // Offsets from the left corner under the floor, vertical, spread out; the occupied band
  private ordinatesX(d: ElevWall, floor: number, x0: number, x1: number): Rect {
    const xs = new Set<number>([0, d.length]);
    for (const p of d.points) xs.add(Math.round(p.x));
    for (const b of d.boxes) xs.add(Math.round(b.x));
    for (const v of d.water ?? []) xs.add(Math.round(v.x));
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

  // Heights from the floor on the right (dir 1) or left (-1); the ceiling gets "*" if its height is an assumption
  private ordinatesY(d: ElevWall, edge: number, floor: number, top: number, dir: 1 | -1): Rect {
    const { height, height_assumed } = this.data;
    const ys = new Set<number>([height]);
    for (const p of d.points) ys.add(Math.round(p.y));
    for (const b of d.boxes) ys.add(Math.round(b.y));
    for (const v of d.water ?? []) ys.add(Math.round(v.y));
    if (d.board) ys.add(Math.round(d.board.y));
    const values = [...ys].sort((a, b) => b - a);  // top to bottom: ascending on screen
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
