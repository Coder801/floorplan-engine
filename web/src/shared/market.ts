// Market prices on the studio price page: the period footnote and the deviation from the median

import type { MarketPeriod } from "./types";

// "2026-03" → "березень 2026 р." in the interface language; "2026" → "2026"
export function monthText(date: string, lng: string): string {
  const [y, m] = date.split("-").map(Number);
  if (!m) return String(y);
  return new Date(y, m - 1, 1).toLocaleDateString(lng, { month: "long", year: "numeric" });
}

// Period of the prices: "2024 – листопад 2026 р."; one date — itself; no dates — ""
export function periodText(p: MarketPeriod, lng: string): string {
  if (!p.start) return "";
  if (p.start === p.end) return monthText(p.start, lng);
  return `${monthText(p.start, lng)} – ${monthText(p.end, lng)}`;
}

// Studio price against the market median, whole percent: +100 — twice the median
export function deviation(price: number | null, median: number | undefined): number | null {
  if (price === null || median === undefined || median <= 0) return null;
  return Math.round((price / median - 1) * 100);
}

// Where the studio price stands in the spread: below the minimum, in the lower quarter,
// the middle half, the upper quarter or above the maximum
export type Place = "below" | "low" | "mid" | "high" | "above";
export function place(price: number, s: { min: number; q1: number; q3: number; max: number }): Place {
  if (price < s.min) return "below";
  if (price > s.max) return "above";
  if (price < s.q1) return "low";
  if (price > s.q3) return "high";
  return "mid";
}
