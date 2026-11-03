// Two-finger pinch on a canvas (sheet, panel): zoom at the point between the fingers and pan
// following it. Fingers are touch pointer events; while there are two, single-finger drag and
// click do not work, and after a pinch no click counts until all fingers are lifted.

type Touch = Pick<PointerEvent, "pointerId" | "pointerType" | "clientX" | "clientY">;

// Pinch step: f is how much larger, (x, y) is the centre in canvas px, (dx, dy) is the centre shift
export interface PinchStep { f: number; x: number; y: number; dx: number; dy: number }

export class Pinch {
  private readonly pts = new Map<number, { x: number; y: number }>();
  private last: { d: number; x: number; y: number } | null = null;
  used = false;   // there was a pinch since the first touch: do not count click or drag

  get busy() { return this.pts.size >= 2; }

  // A finger touched; true means a pinch started (cancel single-finger drag)
  down(ev: Touch): boolean {
    if (ev.pointerType !== "touch") return false;
    if (!this.pts.size) this.used = false;
    this.pts.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (this.pts.size !== 2) return this.busy;
    this.last = this.measure();
    this.used = true;
    return true;
  }

  // A finger moved; the pinch step, or null with fewer than two fingers
  move(ev: Touch, origin: { left: number; top: number }): PinchStep | null {
    if (!this.pts.has(ev.pointerId)) return null;
    this.pts.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (!this.busy || !this.last) return null;
    const m = this.measure(), was = this.last;
    this.last = m;
    return { f: m.d / was.d, x: m.x - origin.left, y: m.y - origin.top, dx: m.x - was.x, dy: m.y - was.y };
  }

  up(ev: Pick<PointerEvent, "pointerId">) {
    this.pts.delete(ev.pointerId);
    this.last = this.busy ? this.measure() : null;
  }

  // Distance between the first two fingers and the midpoint between them
  private measure() {
    const [a, b] = [...this.pts.values()];
    return { d: Math.max(Math.hypot(b.x - a.x, b.y - a.y), 1), x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  }
}
