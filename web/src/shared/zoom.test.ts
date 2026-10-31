import { beforeEach, describe, expect, it } from "vitest";
import i18n from "@/shared/i18n";
import { clampStep, PinchSteps, rulerLength, stepBelow, WheelSteps, zoomLabel } from "./zoom";

describe("шаги масштаба", () => {
  it("за крайние шаги не выйти", () => {
    expect(clampStep(-1)).toBe(0);
    expect(clampStep(9)).toBe(4);
    expect(zoomLabel(1)).toBe("150%");
  });

  it("наезд — крупнейший шаг не больше нужного", () => {
    expect(stepBelow(0.5)).toBe(0);
    expect(stepBelow(2.4)).toBe(2);
    expect(stepBelow(10)).toBe(4);
  });

  it("колесо: прокрутка копится до шага, после шага — пауза", () => {
    const w = new WheelSteps();
    expect(w.push(-20, 0)).toBe(0);
    expect(w.push(-25, 10)).toBe(1);
    expect(w.push(-100, 50)).toBe(0);   // инерция тачпада
    expect(w.push(100, 300)).toBe(-1);
  });

  it("щипок: шаг — когда пальцы развели в 1,3 раза", () => {
    const p = new PinchSteps();
    expect(p.push(1.2)).toBe(0);
    expect(p.push(1.1)).toBe(1);
    expect(p.push(0.7)).toBe(-1);
  });
});

describe("линейка", () => {
  beforeEach(async () => { await i18n.changeLanguage("ru"); });

  it("круглая длина около 100 px", () => {
    expect(rulerLength(0.2)).toEqual({ mm: 500, px: 100, label: "500 мм" });
    expect(rulerLength(0.05)).toMatchObject({ mm: 2000, label: "2 м" });
    expect(rulerLength(1)).toMatchObject({ mm: 100, label: "100 мм" });
  });

  it("единицы — на языке интерфейса", async () => {
    await i18n.changeLanguage("en");
    expect(rulerLength(0.05).label).toBe("2 m");
  });
});
