// Question cards (widgets/Questions): what state an answer is in, the order of the list, what the
// viewer sends. Pure functions; the answer format is model/intake.py, Answers.

import type { Question } from "./types";

// pending: answered, waits for the studio; returned: the studio sent the answer back with a comment
export type Status = "open" | "pending" | "returned" | "answered" | "accepted" | "resolved";
export type Group = "open" | "pending" | "closed";
export type Answer = number | string | string[] | { accept: true } | { text: string };

const SEVERITY: Record<string, number> = { critical: 0, major: 1, minor: 2 };

// By the answer, not by the report alone: a text answer does not rebuild the project
export function statusOf(answer: unknown): Status {
  if (answer && typeof answer === "object") {
    const o = answer as { accept?: boolean; text?: string; resolved?: boolean; returned?: string };
    if (o.accept) return "accepted";
    if ("text" in o) return o.resolved ? "resolved" : o.returned ? "returned" : "pending";
  }
  return answer === undefined || answer === null ? "open" : "answered";
}

// A sent-back answer needs an answer again
export const groupOf = (s: Status): Group => (s === "returned" ? "open" : s === "open" || s === "pending" ? s : "closed");

// A client question only clarifies: any answer goes as { text } and never into the model
export const forClient = (q: { audience?: string }) => q.audience === "client";

// The studio's comment on a sent-back answer
export function returnedComment(answer: unknown): string | null {
  const o = answer as { returned?: unknown } | null;
  return o && typeof o === "object" && typeof o.returned === "string" ? o.returned : null;
}

// Groups in order, the most important first inside a group
export function listOrder(qs: Question[], answers: Record<string, unknown>): Map<string, Group> {
  const rank: Group[] = ["open", "pending", "closed"];
  const rows = qs.map((q, k) => ({ q, k, group: groupOf(statusOf(answers[q.id])) }));
  rows.sort((a, b) => rank.indexOf(a.group) - rank.indexOf(b.group)
    || (SEVERITY[a.q.severity] ?? 9) - (SEVERITY[b.q.severity] ?? 9) || a.k - b.k);
  return new Map(rows.map((r) => [r.q.id, r.group]));
}

// The order stays while the panel is open; questions that appeared go to the "need an answer" group
export function keepOrder(order: Map<string, Group>, qs: Question[]): Map<string, Group> {
  const known = new Set(qs.map((q) => q.id));
  const kept = new Map([...order].filter(([id]) => known.has(id)));
  for (const q of qs) if (!kept.has(q.id)) kept.set(q.id, "open");
  return kept;
}

// The next question without an answer after this one, then from the start of the list
export function nextOpen(ids: string[], statusById: (id: string) => Status, after: string): string | null {
  const from = ids.indexOf(after);
  const ring = [...ids.slice(from + 1), ...ids.slice(0, Math.max(from, 0))];
  return ring.find((id) => groupOf(statusById(id)) === "open") ?? null;
}

// A number as people type it: a comma is fine, spaces are not part of it
export function parseNumber(text: string): number | null {
  const s = text.trim().replace(/\s+/g, "").replace(",", ".");
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

export const plainNumber = (v: unknown) => String(v).replace(/\.0+$/, "");

// The first phrase of a check message: the rest lists walls and is for the studio
export const shortMessage = (message: string) => message.split(/\. (?=[А-ЯЁЇІЄ])/)[0];

// The model field of a question → the object on the sheet (тип:id, as in .epd objects)
const OBJECTS: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^points\.([^.]+)/, (m) => `point:${m[1]}`],
  [/^rooms\.[^.]+\.openings\.([^.]+)/, (m) => `opening:${m[1]}`],
  [/^rooms\.([^.]+)\.walls\.([^.]+)/, (m) => `wall:${m[1]}.${m[2]}`],
  [/^rooms\.([^.]+)/, (m) => `room:${m[1]}`],
  [/^board(\.|$)/, () => "board:board"],
  [/^led_strips\.([^.]+)/, (m) => `led_strip:${m[1]}`],
  [/^risers\.([^.]+)/, (m) => `riser:${m[1]}`],
  [/^fixtures\.([^.]+)/, (m) => `fixture:${m[1]}`],
  [/^obstacles\.([^.]+)/, (m) => `obstacle:${m[1]}`],
];

export function objectOf(target: string | undefined): string | null {
  if (!target) return null;
  for (const [pattern, key] of OBJECTS) {
    const m = target.match(pattern);
    if (m) return key(m);
  }
  return null;
}

// Where "show" leads: an object on the sheet of its stage; panel questions — the "Panel" tab,
// they have no object on it; a list of groups is chosen in its "Backup" mode. null: nothing to
// show (no such sheet, or no object)
export const RESERVE_KEY = "reserve";
export function shownOn(q: Question, stages: string[]): { stage: string; key: string | null } | null {
  if (!stages.includes(q.stage)) return null;
  if (q.answer === "groups") return { stage: q.stage, key: RESERVE_KEY };
  const key = objectOf(q.target);
  return key || q.stage === "panel" ? { stage: q.stage, key } : null;
}

// What survives closing the panel: typed answers and the open question
export interface QuestionsMemory { drafts: Record<string, string>; expanded?: string | null }
