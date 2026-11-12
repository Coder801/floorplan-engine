// Product feedback without React (tests in shared.test.ts): the next status of the quick button,
// who wrote it, what the page attached, and a changed item put back into the loaded page.
import type { FeedbackItem, FeedbackPage, FeedbackStatus } from "./types";

export const FEEDBACK_STATUSES: FeedbackStatus[] = ["new", "seen", "done"];
export const FEEDBACK_KINDS = ["bug", "idea", "other"];

/** new → seen → done; done has no next. */
export function nextStatus(s: FeedbackStatus): FeedbackStatus | null {
  const i = FEEDBACK_STATUSES.indexOf(s);
  return i >= 0 && i < FEEDBACK_STATUSES.length - 1 ? FEEDBACK_STATUSES[i + 1] : null;
}

/** The author: the name, else the e-mail, else the access code label; nobody — "—". */
export function authorOf(a: FeedbackItem["author"]): string {
  if (!a) return "—";
  return a.name || a.email || (a.code_label ? `код «${a.code_label}»` : "—");
}

const CONTEXT: [string, string][] = [["sheet", "лист"], ["version", "версия"], ["viewport", "экран"], ["path", "адрес"]];

/** What the page attached, as "лист: plan" pairs in a fixed order; empty values are skipped. */
export function contextOf(ctx: FeedbackItem["context"]): string[] {
  if (!ctx) return [];
  return CONTEXT.filter(([k]) => ctx[k] != null && ctx[k] !== "").map(([k, label]) => `${label}: ${String(ctx[k])}`);
}

/** The browser line of the context, for the hint. */
export const agentOf = (ctx: FeedbackItem["context"]) =>
  (ctx && typeof ctx.user_agent === "string" ? ctx.user_agent : "");

/** The server's answer to a change replaces the item in place; the status counts move with it.
 *  The item stays in the list even if it no longer fits the status filter: it is still being read. */
export function applyChange(page: FeedbackPage, item: FeedbackItem): FeedbackPage {
  const old = page.items.find((i) => i.id === item.id);
  const counts = { ...page.counts };
  if (old && old.status !== item.status) {
    counts[old.status] = Math.max(0, (counts[old.status] ?? 0) - 1);
    counts[item.status] = (counts[item.status] ?? 0) + 1;
  }
  return { ...page, counts, items: page.items.map((i) => (i.id === item.id ? item : i)) };
}
