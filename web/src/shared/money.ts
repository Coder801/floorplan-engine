// Money on the page: every amount with kopecks ("76,00 грн", "1 587,50"), every sum the page
// itself counts rounded to kopecks. Quantities (metres, pieces, kW) are not money: they keep
// their own formats (work.ts qty)

// Rounded to kopecks, half up as the backend (model/money.py): 0.1 + 0.2 → 0.3, 1.005 → 1.01,
// 1234.005 → 1234.01. The value goes through its shortest decimal form first (15 significant
// digits), so a binary just-below half (1234.00499…) rounds as the decimal the user typed
export function cents(value: number): number {
  const hundredths = Number((Math.abs(value) * 100).toPrecision(15));
  const r = Math.round(hundredths) / 100;
  return value < 0 ? -r : r;
}

const TWO = { minimumFractionDigits: 2, maximumFractionDigits: 2 } as const;

// An amount in the locale (locale() of i18n): always two decimals. The currency: an ISO code
// (UAH) — the locale's currency format; anything else ("грн", as the estimates write it) — the
// number and the word; empty — the number alone (the column heading names the currency)
export function money(value: number, currency: string, locale: string): string {
  const v = cents(value);
  if (/^[A-Z]{3}$/.test(currency)) {
    try {
      return new Intl.NumberFormat(locale, { ...TWO, style: "currency", currency, currencyDisplay: "narrowSymbol" }).format(v);
    } catch { /* an unknown code: as a word below */ }
  }
  const n = new Intl.NumberFormat(locale, TWO).format(v);
  return currency ? `${n} ${currency}` : n;
}

// An amount for a price field: two decimals, the locale's decimal sign, no thousands spaces
// ("76,50" / "76.50"); null — an empty field
export const amountText = (value: number | null, locale: string) =>
  value === null ? "" : new Intl.NumberFormat(locale, { ...TWO, useGrouping: false }).format(cents(value));

// A number typed by a person: comma or dot, spaces ("76", "76,5", "1 587.50"); empty — null
// (as planned / no price); not a number or below zero — undefined (refused)
export function parseAmount(text: string): number | null | undefined {
  const s = text.replace(/[\s  ]/g, "").replace(",", ".");
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) && n >= 0 ? n : undefined;
}

// A typed price: as parseAmount, rounded to kopecks
export function parseMoney(text: string): number | null | undefined {
  const n = parseAmount(text);
  return typeof n === "number" ? cents(n) : n;
}

// A price field after it loses focus: a valid amount shown back with two decimals, anything
// else left as typed (it stays red)
export function tidyAmount(text: string, locale: string): string {
  const n = parseMoney(text);
  return typeof n === "number" ? amountText(n, locale) : text;
}
