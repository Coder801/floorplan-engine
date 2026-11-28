// Question threads on the page (widgets/Threads, widgets/ThreadCard): the tabs by audience, the
// order of the list, what a person may do in a thread. Pure functions; the data and whose turn it
// is (waiting_for, waiting_for_you) — the server, shared/threads.ts; the rules —
// docs/question-threads.md and docs/service-api.md, «Просмотр: вопросы и треды».

import type { Thread, ThreadMessage, ThreadState } from "./threads";
import type { Audience, Question } from "./types";

// How often an open card asks for its thread while the AI checks the accepted answer, ms
export const POLL_MS = 3000;

export const AUDIENCES: Audience[] = ["client", "installer", "studio"];

// A free thread (no question) is the studio's
export const audienceOf = (t: Thread): Audience => t.question?.audience ?? "studio";
export const isLive = (state: ThreadState) => state === "open" || state === "checking";

const SEVERITY: Record<string, number> = { critical: 0, major: 1, minor: 2 };

// Live first, waiting for this person first among them, then by weight, then oldest first;
// finished ones — the newest first
export function threadOrder(threads: Thread[]): Thread[] {
  const rank = (t: Thread) => (!isLive(t.state) ? 2 : t.waiting_for_you ? 0 : 1);
  return [...threads].sort((a, b) => rank(a) - rank(b)
    || (rank(a) === 2 ? (b.closed_at ?? b.created_at).localeCompare(a.closed_at ?? a.created_at) : 0)
    || (SEVERITY[a.question?.severity ?? ""] ?? 9) - (SEVERITY[b.question?.severity ?? ""] ?? 9)
    || a.created_at.localeCompare(b.created_at));
}

export interface TabCount { audience: Audience; live: number; waiting: number; total: number }

// The studio's tabs: every audience, how many threads are live and wait for it
export function tabCounts(threads: Thread[]): TabCount[] {
  return AUDIENCES.map((audience) => {
    const own = threads.filter((t) => audienceOf(t) === audience);
    return {
      audience, total: own.length,
      live: own.filter((t) => isLive(t.state)).length,
      waiting: own.filter((t) => t.waiting_for_you).length,
    };
  });
}

// The tab the studio opens on: what waits for it, else what is live, else the client's
export function firstTab(counts: TabCount[]): Audience {
  return (counts.find((c) => c.waiting) ?? counts.find((c) => c.live) ?? counts[0]).audience;
}

// A question answered by a form (decision 5 of the plan): a value, a choice, groups of the panel
// (code questions panel_…, heating_… are such) asked of the studio. Its thread is for discussion:
// the server does not accept a message of it as the answer (409). A question to the client or the
// installer only clarifies, of any kind: answered by a message, accepted by the studio
export const answeredByForm = (kind: Question["answer"] | undefined, audience: Question["audience"] | undefined): boolean =>
  kind !== undefined && kind !== "text" && (audience ?? "studio") === "studio";

// What a person may do in a thread (docs/service-api.md; decision 2026-11-28: a thread that is not
// open only reads): write — with the right answer or review; accept a message as the answer — the
// studio (review), not in a studio form question; close — the studio. All only in an open thread
export interface ThreadRights { write: boolean; accept: boolean; close: boolean }
export function rightsOf(t: Pick<Thread, "state" | "question">, can: { answer?: boolean; review?: boolean } | undefined): ThreadRights {
  const open = t.state === "open";
  const review = can?.review === true;
  return {
    write: open && (review || can?.answer === true),
    accept: open && review && !answeredByForm(t.question?.kind, t.question?.audience),
    close: open && review,
  };
}

export const acceptable = (m: ThreadMessage) => m.author === "user" && m.text.trim() !== "";

// The last message that says something, for a folded row
export function lastWords(t: Thread): ThreadMessage | null {
  return [...t.messages].reverse().find((m) => m.text.trim() !== "") ?? null;
}

// The answer accepted in the previous thread of the chain: quoted at the top of a follow-up
export function acceptedIn(t: Thread | undefined): ThreadMessage | null {
  if (!t) return null;
  return t.messages.find((m) => m.accepted || m.id === t.accepted_message_id) ?? null;
}
