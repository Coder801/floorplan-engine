import { describe, expect, it } from "vitest";
import { amountText, cents, money, parseAmount, parseMoney, tidyAmount } from "./money";

// Intl separates thousands with a no-break space (U+00A0 or U+202F): any space is one here
const plain = (s: string) => s.replace(/[  ]/g, " ");

describe("cents", () => {
  it("округляет до копеек, без хвостов двоичной дроби", () => {
    expect(cents(0.1 + 0.2)).toBe(0.3);
    expect(cents(1.005)).toBe(1.01);
    expect(cents(0.005)).toBe(0.01);
    expect(cents(-1.005)).toBe(-1.01);
    expect(cents(76)).toBe(76);
    expect(cents(1234.005)).toBe(1234.01); // as the backend, half up past EPSILON range
    expect(cents(2.675)).toBe(2.68);
    expect(cents(1234.004)).toBe(1234);
  });
});

describe("money", () => {
  it("всегда две цифры после запятой — на каждом языке", () => {
    expect(plain(money(76, "", "ru-RU"))).toBe("76,00");
    expect(plain(money(1587.5, "", "ru-RU"))).toBe("1 587,50");
    expect(plain(money(1587.5, "", "uk-UA"))).toBe("1 587,50");
    expect(money(1587.5, "", "en-GB")).toBe("1,587.50");
    expect(plain(money(0.005, "", "ru-RU"))).toBe("0,01");
    expect(plain(money(1e6, "", "ru-RU"))).toBe("1 000 000,00");
    expect(plain(money(1e6, "", "uk-UA"))).toBe("1 000 000,00");
    expect(money(1e6, "", "en-GB")).toBe("1,000,000.00");
  });
  it("слово валюты из сметы или код ISO", () => {
    expect(plain(money(20719.6, "грн", "ru-RU"))).toBe("20 719,60 грн");
    expect(plain(money(1500, "грн", "uk-UA"))).toBe("1 500,00 грн");
    expect(money(1500, "EUR", "en-GB")).toBe("€1,500.00");
    expect(money(76, "XYZ1", "en-GB")).toBe("76.00 XYZ1");
  });
});

describe("поле цены", () => {
  it("принимает 76, 76,5 и 76.50; пусто — null, неверное — undefined", () => {
    expect(parseAmount("76")).toBe(76);
    expect(parseAmount("76,5")).toBe(76.5);
    expect(parseAmount("76.50")).toBe(76.5);
    expect(parseAmount("1 234,5")).toBe(1234.5);
    expect(parseAmount("")).toBeNull();
    expect(parseAmount("abc")).toBeUndefined();
    expect(parseAmount("-3")).toBeUndefined();
    expect(parseMoney("12,345")).toBe(12.35);
    expect(parseMoney("")).toBeNull();
  });
  it("после ухода из поля — две цифры, без пробелов разрядов; неверное остаётся как есть", () => {
    expect(tidyAmount("76", "ru-RU")).toBe("76,00");
    expect(tidyAmount("76,5", "uk-UA")).toBe("76,50");
    expect(tidyAmount("1587.5", "en-GB")).toBe("1587.50");
    expect(tidyAmount("abc", "ru-RU")).toBe("abc");
    expect(tidyAmount("", "ru-RU")).toBe("");
    expect(amountText(null, "ru-RU")).toBe("");
    expect(amountText(1587.5, "ru-RU")).toBe("1587,50");
  });
});
