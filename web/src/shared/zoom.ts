// Масштаб холстов (лист, щит, развёртка) — пять фиксированных шагов от «вписано целиком»:
// колесо, щипок и шкала справа (ZoomRail) переходят на шаг плавно (Glide), остановиться
// между шагами и выйти за них нельзя. Внизу справа — линейка (ScaleBar) в мм объекта:
// модели, щита, стены.

import i18n from "@/shared/i18n";
import { REDUCED_MOTION } from "./consts";

export const ZOOM_STEPS = [1, 1.5, 2, 3, 4] as const;
export const LAST_STEP = ZOOM_STEPS.length - 1;

// Что показывать под чертежом: шаг, подпись и сколько px экрана в мм объекта (нет — без линейки)
export interface Zoom {
  step: number;
  label: string;
  pxPerMm: number | null;
}

export const zoomLabel = (step: number) => `${Math.round(ZOOM_STEPS[step] * 100)}%`;
export const clampStep = (step: number) => Math.min(Math.max(Math.round(step), 0), LAST_STEP);

// Крупнейший шаг, не больше ratio (наезд на объект: не крупнее нужного)
export function stepBelow(ratio: number): number {
  let k = 0;
  while (k < LAST_STEP && ZOOM_STEPS[k + 1] <= ratio + 1e-9) k++;
  return k;
}

export const RAIL_PX = 52;  // справа у чертежа — шкала масштаба: при «вписать» это место свободно

const GLIDE_MS = 220;

export interface View2D { scale: number; ox: number; oy: number }

// Плавный переход к масштабу to у точки (x, y) экрана: точка под ней стоит на месте
// (экран = o ± мм·scale — у листа и щита y вниз, у развёртки вверх: формула та же),
// масштаб меняется по логарифму. Без анимации (prefers-reduced-motion) — сразу
export class Glide {
  private frame = 0;

  stop() { cancelAnimationFrame(this.frame); this.frame = 0; }

  run(from: View2D, to: number, x: number, y: number, apply: (v: View2D) => void) {
    this.stop();
    const at = (s: number) => ({
      scale: s, ox: x - (x - from.ox) * (s / from.scale), oy: y - (y - from.oy) * (s / from.scale),
    });
    if (REDUCED_MOTION) { apply(at(to)); return; }
    const t0 = performance.now();
    const step = (now: number) => {
      const t = Math.min((now - t0) / GLIDE_MS, 1), e = 1 - (1 - t) ** 3;
      apply(at(from.scale * (to / from.scale) ** e));
      this.frame = t < 1 ? requestAnimationFrame(step) : 0;
    };
    this.frame = requestAnimationFrame(step);
  }
}

const WHEEL_PX = 40;       // накопленная прокрутка на один шаг
const WHEEL_PAUSE = 180;   // мс после шага: инерция тачпада не перескакивает через шаги

// Колесо и тачпад: прокрутка копится до шага, после шага — пауза
export class WheelSteps {
  private acc = 0;
  private until = 0;

  push(deltaY: number, now: number): -1 | 0 | 1 {
    if (now < this.until) return 0;
    this.acc += deltaY;
    if (Math.abs(this.acc) < WHEEL_PX) return 0;
    const dir = this.acc < 0 ? 1 : -1;  // от себя — крупнее
    this.acc = 0;
    this.until = now + WHEEL_PAUSE;
    return dir;
  }
}

const PINCH_STEP = 1.3;  // во сколько раз развести пальцы на один шаг

// Щипок: множитель копится до шага
export class PinchSteps {
  private acc = 1;

  push(f: number): -1 | 0 | 1 {
    this.acc *= f;
    if (this.acc >= PINCH_STEP) { this.acc = 1; return 1; }
    if (this.acc <= 1 / PINCH_STEP) { this.acc = 1; return -1; }
    return 0;
  }
}

// Линейка: круглая длина (1, 2, 5 × 10ⁿ мм), чтобы на экране было около target px
export function rulerLength(pxPerMm: number, target = 100): { mm: number; px: number; label: string } {
  const raw = target / pxPerMm;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const mm = [1, 2, 5, 10].map((m) => m * pow).reduce((a, b) => (Math.abs(b - raw) < Math.abs(a - raw) ? b : a));
  const label = mm >= 1000 ? `${String(mm / 1000).replace(".", ",")} ${i18n.t("units.m")}` : `${mm} ${i18n.t("units.mm")}`;
  return { mm, px: mm * pxPerMm, label };
}
