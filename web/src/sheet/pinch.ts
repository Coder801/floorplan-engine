// Щипок двумя пальцами на холсте (лист, щит): масштаб у точки между пальцами и сдвиг вслед
// за ней. Пальцы — pointer-события касания; пока пальцев два, перетаскивание одним и клик
// не работают, а после щипка клик не засчитывается, пока не отпущены все пальцы.

type Touch = Pick<PointerEvent, "pointerId" | "pointerType" | "clientX" | "clientY">;

// Шаг щипка: f — во сколько крупнее, (x, y) — центр в px холста, (dx, dy) — сдвиг центра
export interface PinchStep { f: number; x: number; y: number; dx: number; dy: number }

export class Pinch {
  private readonly pts = new Map<number, { x: number; y: number }>();
  private last: { d: number; x: number; y: number } | null = null;
  used = false;   // с первого касания был щипок — клик и перетаскивание не засчитывать

  get busy() { return this.pts.size >= 2; }

  // Палец коснулся; true — начался щипок (перетаскивание одним пальцем отменить)
  down(ev: Touch): boolean {
    if (ev.pointerType !== "touch") return false;
    if (!this.pts.size) this.used = false;
    this.pts.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (this.pts.size !== 2) return this.busy;
    this.last = this.measure();
    this.used = true;
    return true;
  }

  // Палец сдвинулся; шаг щипка или null, если пальцев меньше двух
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

  // Расстояние между первыми двумя пальцами и середина между ними
  private measure() {
    const [a, b] = [...this.pts.values()];
    return { d: Math.max(Math.hypot(b.x - a.x, b.y - a.y), 1), x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  }
}
