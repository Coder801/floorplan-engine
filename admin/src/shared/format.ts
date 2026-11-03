// Dates and people for tables: short and in the reader's time zone.
import type { UserBrief } from "./types";

const two = (n: number) => String(n).padStart(2, "0");

/** "03.11.2026 14:05"; without the time — "03.11.2026"; no date — "—". */
export function date(iso: string | null | undefined, time = true): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const day = `${two(d.getDate())}.${two(d.getMonth() + 1)}.${d.getFullYear()}`;
  return time ? `${day} ${two(d.getHours())}:${two(d.getMinutes())}` : day;
}

/** "5 мин", "3 ч", "2 дн" назад; older than a month — the date. */
export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const s = (now - new Date(iso).getTime()) / 1000;
  if (Number.isNaN(s)) return "—";
  if (s < 60) return "сейчас";
  if (s < 3600) return `${Math.floor(s / 60)} мин`;
  if (s < 86400) return `${Math.floor(s / 3600)} ч`;
  if (s < 30 * 86400) return `${Math.floor(s / 86400)} дн`;
  return date(iso, false);
}

/** Who this is: the name, else the e-mail, else the phone. */
export const who = (u: Pick<UserBrief, "name" | "email" | "phone"> | null | undefined) =>
  !u ? "—" : u.name || u.email || u.phone || "без имени";

/** How to reach them: the e-mail and/or the phone. */
export const contact = (u: Pick<UserBrief, "email" | "phone">) =>
  [u.email, u.phone].filter(Boolean).join(" · ") || "—";
