// The panel drawing on the current canvas transform, in panel mm: devices on their rails,
// busbars, feeds and group wires, the input, the inverter and the battery box. Power from the
// top: main switch → relay with a jumper on the bottom terminals; from the relay output, the
// shared device busbar and trunks along the left wall to the row busbars (main; backup from the
// ATS; N from the N input to the N terminal block and branches to the neutral busbars). A group
// wire is a thin line in the group colour from the bottom terminal into a bundle under the rail,
// as a bundle to the right wall, and past the enclosure at an angle to its label; L, N, PE input
// from the top, PE terminal block at the top and N at the bottom of the enclosure. A hybrid
// inverter gets a battery box: battery and solar string wires go up into the inverter's BAT and
// PV inputs, the battery sits under the box.

import { palette } from "@/shared/palette";
import type { PanelData } from "@/shared/types";
import { clip, plate, rendererFor, SCREW, text, type Pen } from "./catalog";
import { BACKUP, busSegments, CHAIN, groupPath, LABELS, MODULE, termX,
         type PanelLayout, type Placed, type Row } from "./layout";
import { batteryCabinet, enclosureBox, inverterBody, LABEL, rail, terminalBlock } from "./parts";

export const WIRE = 2.2;   // wire width, panel mm
export const TITLE = 9;
const THICK_WIRE = WIRE * 1.6;  // battery cables
const INPUT_WIRE = "#8b4513";
const RESERVE = "#2e8b57";
const PE = "#2e8b2e";
const PE_STRIPE = "#e3c200";  // PE is yellow-green
// The enclosure interior is light in any theme: busbars and the wire underlay inside use light
// theme colours, not screenColor
const INSIDE_HALO = "#ffffff", COMB = "#5a5a5a";
const N = "#1f5fbf";
const PE_BODY = "#3f9b4a";    // PE terminal block body
const N_BODY = "#2f6fc4";     // N terminal block body
const ID = 4.4;            // designation on the device plate
// Above the devices: phase busbar, neutral busbar (for RCBOs), backup feed entry
const L_COMB = 5, N_COMB = 10;
const approach = (row: Row) => row.devTop - (row.kind === "double" ? 15 : 11);
// Under the shared devices, jumper lanes: input N, input → relay and the shared busbar,
// main network trunk, backup trunk, surge protector PE (below: inverter feed, layout.FEED_LANE)
const BELOW = { n: 2.5, chain: 5.5, main: 8.5, reserve: 11.5, spd: 14.5 } as const;
// Trunks along the left wall (no group lanes left of the devices)
const TRUNK = { n: 10, main: 18, reserve: 26, spd: 4 } as const;
// Inverter feed: N under L; inverter PE as a trunk along the right wall (PE_TRUNK from it)
const CORE = 2.5;
const PE_TRUNK = 8;
const GROUP_WIRE = 1.4;    // group wire, panel mm: no thicker than the bundle step
const DC_PLUS = "#c62828", DC_MINUS = "#1e1e1e";  // DC wires: "+" red, "−" black

export class PanelPainter {
  constructor(private readonly ctx: CanvasRenderingContext2D, private readonly lay: PanelLayout,
              private readonly data: PanelData, private readonly language?: string) {}

  // Devices, wires, the input and the inverter; the highlight on top is PanelView's
  paint(pen: Pen) {
    const l = this.lay, d = this.data;
    const enc = l.enclosure;
    text(pen, `${d.texts.title} · ${enc.title} · ${d.totals.modules}/${enc.rows * enc.per_row} DIN`,
         0, -TITLE, TITLE, pen.ink, "left");

    const b = l.box;
    enclosureBox(pen, b, enc);
    terminalBlock(pen, l.pe, "PE", PE_BODY, l.terminals);
    terminalBlock(pen, l.n, "N", N_BODY, l.terminals);

    const byId = new Map(l.placed.map((p) => [p.dev.id, p]));
    for (const y of l.rails) rail(pen, b.x + 12, b.x + b.w - 12, y);  // including empty ones
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

    // Input from the top: L and N into the main switch, PE into the input terminal of the PE block
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
  }

  private device(pen: Pen, p: Placed) {
    const { ctx } = pen, dev = p.dev;
    rendererFor(dev)(pen, dev, p);
    // Marking on the cover plate: the designation on the group colour, like its lines on the sheets
    const color = (dev.group && this.data.groups[dev.group]?.color) || null;
    const t = plate(p);
    if (color) { ctx.fillStyle = color; ctx.fillRect(t.x, t.y, t.w, t.h); }
    // Narrow plate: first drop the "*" (the assumption shows in the group label), then go smaller
    ctx.font = `${ID}px ${pen.font}`;
    const id = dev.assumed && ctx.measureText(dev.id + "*").width <= t.w ? dev.id + "*" : dev.id;
    const size = Math.min(ID, (ID * t.w) / ctx.measureText(id).width);
    text(pen, id, t.x + t.w / 2, t.y + t.h / 2 + 0.2, size, color && dark(color) ? "#ffffff" : "#1e1e1e");
    if (dev.kind === "spd") {  // surge protector to the PE block
      // Up along the left wall and through the gap under the terminal block: never crosses the group lanes
      const pe = this.lay.pe, cx = p.x + p.w / 2, x = termX(pe, 1);
      const y = this.lay.rows[p.row].gutterTop + BELOW.spd, band = pe.y + pe.h + 6, side = TRUNK.spd;
      this.wire(PE, [[cx, p.y + p.h - SCREW], [cx, y], [side, y], [side, band], [x, band], [x, pe.y + pe.h - 6]],
                PE_STRIPE);
    }
  }

  // Group wire: a thin line in the group colour along the bundle (groupPath), the label in the
  // column on the right. Inverter feed: L and N along the same lane, then on to the inverter (external)
  private outWire(pen: Pen, p: Placed) {
    if (p.lane === null) return;
    const g = p.dev.group ? this.data.groups[p.dev.group] : undefined;
    const cx = p.x + MODULE / 2, right = this.lay.box.x + this.lay.box.w, from = p.y + p.h - SCREW;
    if (!g) {  // inverter feed 2P
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
    // "QF6 Освітлення — Санвузол · 3x1.5 · 0,50 кВт*": the purpose in ink, cable and power in
    // the group colour
    const tail = ` · ${g.cable || "—"} · ${(g.power / 1000).toFixed(2).replace(".", ",")} кВт${g.assumed ? "*" : ""}`;
    ctx.font = `${LABEL}px ${pen.font}`;
    const room = LABELS - 8 - ctx.measureText(tail).width;
    const lead = clip(pen, `${p.dev.id}  ${g.purpose}`, room, LABEL);
    const x = this.lay.labelX + 1;
    text(pen, lead, x, p.label, LABEL, pen.ink, "left");
    ctx.font = `${LABEL}px ${pen.font}`;
    text(pen, tail, x + ctx.measureText(lead).width, p.label, LABEL, color, "left");
  }

  // Busbars of a group row above the devices: phase (main and backup in sections), teeth into
  // the top terminal of the first module; RCBOs also get a neutral one, one per row, teeth into
  // the second module (N)
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

  // Busbar of the shared devices after the main switch and relay (surge protector, ATS input I,
  // inverter feed); the inverter output is not fed from the grid
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

  // Wire with an underlay in the background colour, so a crossing shows which is on top; inside
  // the enclosure the underlay is light (the interior is light in any theme), outside it is the
  // paper colour; stripe adds stripes of a second colour (PE)
  private wire(color: string, pts: [number, number][], stripe?: string, width = WIRE) {
    const { ctx } = this, boxes = [this.lay.box, ...(this.lay.dc ? [this.lay.dc.box] : [])];
    ctx.lineJoin = "round"; ctx.lineCap = "round";
    ctx.beginPath();
    tracePath(ctx, pts);
    // A thin wire's underlay is narrower, so in a bundle it does not cover its neighbours
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

  // Power distribution in the panel. Under the shared devices: main switch → relay via the
  // bottom terminals; from the output of the last of them (phase in the first module for the
  // main switch, the last module for the relay) into the shared busbar and as a trunk along the
  // left wall to the phase busbars of the group rows; from the ATS output, a backup trunk to the
  // backup sections (entering above the busbar); input N along the wall to the N terminal block,
  // with branches to the RCBO neutral busbars
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

  // Inverter or generator plug right of the labels; five wires from the bottom, no crossings:
  // GRID L, N from the inverter feed along its lane; LOAD L, N through the gap left of the
  // inverter and above the ATS row into input II (the last two modules); PE as a trunk along the
  // right wall into the last terminal of the PE block
  private external(pen: Pen, byId: Map<string, Placed>) {
    const e = this.lay.external!, x = this.data.external!;
    const t = inverterBody(pen, e, x);
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
    // PE goes up along the right wall of the panel to the last terminal of the PE block
    const pe = this.lay.pe, last = termX(pe, this.lay.terminals), peY = pe.y + pe.h + 4;
    const trunk = right - PE_TRUNK, y = bottom + 12;
    this.wire(PE, [[t.pe, bottom], [t.pe, y], [trunk, y], [trunk, peY], [last, peY], [last, pe.y + pe.h - 6]],
              PE_STRIPE);
    if (this.lay.dc && this.data.dc && t.glands) this.dcBox(pen, bottom, t.glands);
  }

  // Battery box: enclosure and devices; from the top terminals up along their own lanes and left
  // into the inverter inputs (battery into BAT+ and BAT−, a solar string as a pair into its PV
  // input); from the bottom terminals of the battery breaker, cables to the battery, solar
  // strings go down and right to their label; a string's surge protector is jumpered to its
  // breaker terminals, PE goes down to its mark
  private dcBox(pen: Pen, invBottom: number, glands: { bat: [number, number]; pv: number[] }) {
    const dc = this.lay.dc!, data = this.data.dc!;
    const enc = dc.enclosure;
    const used = data.devices.reduce((s, d) => s + d.model.modules, 0);
    // Label under the battery: wires to the inverter run above the enclosure, to the battery and panels below it
    text(pen, `${data.texts.title} · ${enc.title} · ${used}/${enc.rows * enc.per_row} DIN`,
         dc.battery.x, dc.battery.y + dc.battery.h + 8, LABEL, pen.ink, "left");
    enclosureBox(pen, dc.box, enc);
    for (const y of dc.rails) rail(pen, dc.box.x + 12, dc.box.x + dc.box.w - 12, y);
    for (const p of dc.placed) this.device(pen, p);
    const poles = (p: Placed) => [p.x + MODULE / 2, p.x + p.w - MODULE / 2];  // "+" and "−"
    // Up to the inverter: in order left to right, the right-hand wire gets the higher lane
    const ups: { x: number; y: number; to: number; color: string; width: number }[] = [];
    const battery = dc.placed.find((p) => p.dev.kind === "dc_battery");
    const strings = dc.placed.filter((p) => p.dev.kind === "dc_breaker");
        if (battery) {
      const [xp, xm] = poles(battery);
      ups.push({ x: xp, y: battery.y + SCREW, to: glands.bat[0], color: DC_PLUS, width: THICK_WIRE });
      ups.push({ x: xm, y: battery.y + SCREW, to: glands.bat[1], color: DC_MINUS, width: THICK_WIRE });
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
    // String surge protector: jumpers to the string breaker terminals, PE down to its mark
    dc.placed.filter((p) => p.dev.kind === "dc_spd").forEach((f, k) => {
      const q = strings[k];
      if (q) {
        const y = f.y + SCREW;
        this.wire(DC_MINUS, [[f.x + 1.5 * MODULE, y], [f.x + 1.5 * MODULE, y - 13], [q.x + 1.5 * MODULE, y - 13]], undefined, 1.2);
        this.wire(DC_PLUS, [[f.x + MODULE / 2, y], [f.x + MODULE / 2, y - 16], [q.x + MODULE / 2, y - 16]], undefined, 1.2);
      }
      const cx = f.x + f.w / 2, from = f.y + f.h - SCREW;
      this.wire(PE, [[cx, from], [cx, from + 16]], PE_STRIPE, 1.6);
      text(pen, "PE", cx, from + 21, 4.5, PE);
    });
    // Solar strings: from the bottom terminals down under the enclosure and right to the label
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

  // The battery cabinet; "+" and "−" terminals on top under the battery breaker poles, cables to
  // its bottom terminals
  private battery(pen: Pen, qb: Placed, [xp, xm]: number[], data: NonNullable<PanelData["dc"]>) {
    const { ctx } = pen, r = this.lay.dc!.battery, b = data.battery;
    batteryCabinet(pen, r, data, this.language);
    const from = qb.y + qb.h - SCREW;
    for (const [x, color, sign] of [[xp, DC_PLUS, "+"], [xm, DC_MINUS, "−"]] as const) {
      ctx.fillStyle = color;
      ctx.beginPath(); ctx.roundRect(x - 5, r.y - 6, 10, 7, 1.5); ctx.fill();
      text(pen, sign, x, r.y - 2.6, 6, "#ffffff");
      this.wire(color, [[x, r.y - 6], [x, from]], undefined, THICK_WIRE);
    }
    const box = this.lay.dc!.box;
    // Left of the battery cables: the solar string wires run on the right
    text(pen, `2×${String(b.cable).replace(".", ",")} мм² · ${b.rating} А`, xp - 7, (box.y + box.h + r.y) / 2,
         5.5, pen.ink, "right");
  }

  // Inverter output breaker → input II of the ATS or switch: from the bottom terminals under
  // the rail left into the last two switch modules from below; L (left pole) higher and into
  // the outermost module, N lower and into the next one: the jumpers do not cross
  private outputJumper(out: Placed, sw: Placed) {
    const y = this.lay.rows[out.row].gutterTop, from = out.y + out.h - SCREW;
    const l = out.x + MODULE / 2, n = out.x + 1.5 * MODULE;
    const tl = sw.x + sw.w - MODULE / 2, tn = sw.x + sw.w - 1.5 * MODULE, into = sw.y + sw.h - SCREW;
    this.wire(N, [[n, from], [n, y + 6.5], [tn, y + 6.5], [tn, into]]);
    this.wire(RESERVE, [[l, from], [l, y + 3], [tl, y + 3], [tl, into]]);
  }

}

// The polyline as the current canvas path
export function tracePath(ctx: CanvasRenderingContext2D, pts: [number, number][]) {
  pts.forEach(([x, y], k) => (k ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
}

// A dark colour gets white text on it
function dark(hex: string): boolean {
  const n = parseInt(hex.replace("#", "").slice(0, 6), 16);
  return 0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255) < 150;
}
