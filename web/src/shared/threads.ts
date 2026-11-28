// Question threads of the database viewer (docs/service-api.md, «Просмотр: вопросы и треды»;
// service/api/viewer_threads.py): every request and response type of /api/projects/{key}/threads…
// lives here. The folder viewer (`floorplan-engine view`) has no threads: GET /threads answers
// 404 there, and the questions panel keeps answers.yaml (widgets/Questions).

import type { Audience, Question } from "./types";
import { base } from "./api";

export type ThreadState = "open" | "checking" | "resolved" | "superseded" | "closed";
export type MessageAuthor = "user" | "analyzer" | "system";

// meta of a message: the AI check (analyzer) — verdict, reason, changes; the quote opening a
// follow-up thread (system) — quote, previous_thread_id
export interface MessageMeta {
  verdict?: "satisfied" | "unsatisfied";
  reason?: string;
  changes?: string[];  // "room.yaml: w2.length 4000 → 4100"
  quote?: string;
  previous_thread_id?: string;
}

export interface ThreadMessage {
  id: string;
  author: MessageAuthor;
  author_label: string;  // a name or «код: Иван»; empty for the analyzer and the system
  role: string;          // the author's project role when written (owner, designer, client…), "" — not known
  text: string;
  meta: MessageMeta;
  created_at: string;    // ISO
  mine: boolean;         // written by the caller
  accepted: boolean;     // the message the studio accepted as the answer
}

// The question of a thread as the server keeps it: a superseded one has left intake.yaml
export interface ThreadQuestion {
  id: string;            // qid, as in intake.yaml (q12) and report.questions
  text: string;
  stage: string;
  audience: Audience;
  kind: Question["answer"];  // value | choice | text | groups
  severity: string;
  assumption: unknown;
  target: string | null;
  unit: string | null;
  options: string[];
  option_labels: Record<string, string>;
  source: string;        // analyzer, studio, code…
  in_intake: boolean;    // in intake.yaml now: not removed, not superseded, not a code question
}

export interface Thread {
  id: string;
  state: ThreadState;
  question: ThreadQuestion | null;  // null — a free thread (not made yet)
  created_at: string;
  closed_at: string | null;
  previous_thread_id: string | null;
  chain: number;                    // the chain length with this thread: 3 — «3-й тред по вопросу»
  accepted_message_id: string | null;
  result_version: number | null;    // the model version the accepted answer made
  messages_count: number;
  messages: ThreadMessage[];        // in the list — the last 3, in a thread — all; oldest first
  waiting_for: Audience | null;     // who acts next in an open thread
  waiting_for_you: boolean;         // that is the caller's side
}

// A thread read alone: all its messages and the earlier threads of its chain the caller sees
export interface ThreadDetail extends Thread {
  previous: Thread[];  // newest first
}

export interface ThreadList {
  threads: Thread[];      // oldest first
  waiting_for_you: number;
}

// A refusal of the server: 403 — no right, 404 — no such thread (or no threads here), 409 — the
// thread is not in a state for this, 422 — a bad body; message — the server's text (in Russian)
export class ThreadError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  if (!r.ok) {
    let d: unknown = null;
    try { d = ((await r.json()) as { detail?: unknown }).detail; } catch { /* not JSON */ }
    throw new ThreadError(r.status, typeof d === "string" && d ? d : `${r.status}: ${r.statusText}`);
  }
  return (await r.json()) as T;
}

const post = (body?: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}),
});
const threads = (key: string) => `${base(key)}/threads`;
const one = (key: string, id: string) => `${threads(key)}/${encodeURIComponent(id)}`;

// What the widgets call: the real API by default, a fake one in stories. Every write answers with
// the thread (all its messages; previous — not sent, the card keeps what it read)
export interface ThreadsApi {
  list: (key: string) => Promise<ThreadList>;
  get: (key: string, id: string) => Promise<ThreadDetail>;
  send: (key: string, id: string, text: string) => Promise<Thread>;
  accept: (key: string, id: string, messageId: string) => Promise<Thread>;
  close: (key: string, id: string, comment?: string) => Promise<Thread>;
}

export const threadsApi: ThreadsApi = {
  list: (key) => call<ThreadList>(threads(key)),
  get: (key, id) => call<ThreadDetail>(one(key, id)),
  send: (key, id, text) => call<Thread>(`${one(key, id)}/messages`, post({ text })),
  accept: (key, id, messageId) => call<Thread>(`${one(key, id)}/accept`, post({ message_id: messageId })),
  close: (key, id, comment) => call<Thread>(`${one(key, id)}/close`, post(comment ? { comment } : undefined)),
};
