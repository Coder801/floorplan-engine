import { describe, expect, it } from "vitest";
import { Pinch } from "./pinch";

const touch = (pointerId: number, clientX: number, clientY: number, pointerType = "touch") =>
  ({ pointerId, pointerType, clientX, clientY });
const origin = { left: 10, top: 20 };

describe("Pinch", () => {
  it("один палец — не щипок", () => {
    const p = new Pinch();
    expect(p.down(touch(1, 100, 100))).toBe(false);
    expect(p.move(touch(1, 120, 100), origin)).toBeNull();
    expect(p.used).toBe(false);
  });

  it("мышь не считается", () => {
    const p = new Pinch();
    p.down(touch(1, 0, 0, "mouse"));
    expect(p.down(touch(2, 100, 0, "mouse"))).toBe(false);
  });

  it("пальцы расходятся — крупнее у точки между ними", () => {
    const p = new Pinch();
    p.down(touch(1, 100, 100));
    expect(p.down(touch(2, 200, 100))).toBe(true);
    const s = p.move(touch(2, 300, 100), origin)!;
    expect(s.f).toBeCloseTo(2);
    expect([s.x, s.y]).toEqual([190, 80]);   // середина (200, 100) в px холста
    expect([s.dx, s.dy]).toEqual([50, 0]);   // середина ушла с 150 на 200
  });

  it("после щипка клик не засчитывается, пока не отпущены все пальцы", () => {
    const p = new Pinch();
    p.down(touch(1, 0, 0)); p.down(touch(2, 100, 0));
    p.up(touch(2, 0, 0));
    expect(p.busy).toBe(false);
    expect(p.move(touch(1, 10, 0), origin)).toBeNull();
    expect(p.used).toBe(true);
    p.up(touch(1, 0, 0));
    p.down(touch(3, 0, 0));
    expect(p.used).toBe(false);
  });
});
