// Threads for stories and tests (no API), in the shapes of docs/service-api.md («Просмотр: вопросы
// и треды»): factories, one thread in every state, and a fake ThreadsApi in memory — a message is
// added, accept puts the thread into checking and the AI check "answers" after checkMs (resolved,
// with an analyzer message) — a thread that is checking when first read too — close closes it.

import type { Thread, ThreadDetail, ThreadList, ThreadMessage, ThreadQuestion, ThreadsApi } from "@/shared/threads";

export const message = (over: Partial<ThreadMessage> = {}): ThreadMessage => ({
  id: "m1", author: "user", author_label: "Иван", role: "client", text: "Телевизор — на стене напротив дивана.",
  meta: {}, created_at: "2026-11-28T10:00:00Z", mine: false, accepted: false, ...over,
});

export const ask = (over: Partial<ThreadQuestion> = {}): ThreadQuestion => ({
  id: "q1", text: "Где будет телевизор в гостиной?", stage: "electrical", audience: "client", kind: "text", severity: "major",
  assumption: null, target: null, unit: null, options: [], option_labels: {}, source: "analyzer", in_intake: true, ...over,
});

export const thread = (over: Partial<ThreadDetail> = {}): ThreadDetail => ({
  id: "t1", state: "open", question: ask(), created_at: "2026-11-27T09:00:00Z", closed_at: null,
  previous_thread_id: null, chain: 1, accepted_message_id: null, result_version: null,
  messages_count: 1, messages: [message()], waiting_for: "studio", waiting_for_you: true, previous: [], ...over,
});

// The list row of a thread: its last 3 messages, no chain
export const summaryOf = (d: ThreadDetail): Thread => {
  const { previous: _, ...rest } = d;
  return { ...rest, messages: d.messages.slice(-3), messages_count: d.messages.length };
};

// The list as the studio sees it
export const listOf = (all: ThreadDetail[]): ThreadList => ({
  threads: all.map(summaryOf), waiting_for_you: all.filter((d) => d.waiting_for_you).length,
});

const analyzerYes = message({
  id: "m3", author: "analyzer", author_label: "", role: "", text: "", created_at: "2026-11-28T12:00:00Z",
  meta: { verdict: "satisfied", reason: "ответ даёт место и высоту ТВ", changes: ["electrical.yaml: points.tv1.wall w3", "electrical.yaml: points.tv1.height 1100"] },
});
const analyzerNo = message({
  id: "m3", author: "analyzer", author_label: "", role: "", text: "", created_at: "2026-11-28T12:00:00Z",
  meta: { verdict: "unsatisfied", reason: "сказано «как на кухне», но размер кухни тоже не известен" },
});

const superseded = thread({
  id: "t4", state: "superseded", accepted_message_id: "m1", closed_at: "2026-11-28T12:00:00Z", waiting_for: null, waiting_for_you: false,
  question: ask({ id: "q4", text: "Какая ширина проёма в кухню?", severity: "critical", stage: "plan", in_intake: false }),
  messages: [message({ text: "Как на кухне.", accepted: true }), analyzerNo],
});

// One thread in every state (as the studio sees them), and a follow-up of the superseded one
export const THREADS: ThreadDetail[] = [
  thread({ id: "t1" }),
  thread({
    id: "t2", state: "checking", accepted_message_id: "m4", waiting_for: null, waiting_for_you: false,
    question: ask({ id: "q2", text: "Нужна ли розетка у кровати слева?", severity: "minor" }),
    messages: [message({ id: "m4", text: "Да, две.", accepted: true })],
  }),
  thread({
    id: "t3", state: "resolved", accepted_message_id: "m1", result_version: 7, closed_at: "2026-11-28T12:00:00Z", waiting_for: null, waiting_for_you: false,
    question: ask({ id: "q3", text: "На какой высоте телевизор в спальне?", in_intake: false }),
    messages: [message({ text: "1100 мм от пола, по центру стены.", accepted: true }), analyzerYes],
  }),
  superseded,
  thread({
    id: "t5", previous_thread_id: "t4", chain: 2, created_at: "2026-11-28T12:00:00Z", waiting_for: "client", waiting_for_you: false,
    question: ask({ id: "q9", text: "Какая ширина проёма в кухню, мм?", severity: "critical", stage: "plan", source: "analyzer" }),
    messages: [
      message({ id: "m5", author: "system", author_label: "", role: "", text: "Прошлый ответ: «Как на кухне.»", meta: { quote: "Как на кухне.", previous_thread_id: "t4" } }),
      message({ id: "m6", author_label: "Олег", role: "designer", text: "Какая высота от пола?", created_at: "2026-11-28T13:00:00Z", mine: true }),
    ],
    previous: [summaryOf(superseded)],
  }),
  thread({
    id: "t6", state: "closed", closed_at: "2026-11-28T13:00:00Z", waiting_for: null, waiting_for_you: false,
    question: ask({ id: "q5", text: "Где стоит стиральная машина?", audience: "installer", severity: "minor", stage: "plumbing" }),
    messages: [message({ author_label: "Сергей", role: "installer", text: "Под раковиной места нет." }),
               message({ id: "m2", author_label: "Олег", role: "designer", text: "Перенесли в ванную, исходники поправлены.", mine: true })],
  }),
  thread({
    id: "t7", waiting_for: "studio", waiting_for_you: true,
    question: ask({ id: "q6", text: "Высота потолка в коридоре?", audience: "studio", kind: "value", stage: "plan", source: "analyzer", assumption: 2700, unit: "mm" }),
    messages: [], messages_count: 0,
  }),
];

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

// The fake server: what the stories click goes into these threads
export function fakeThreadsApi(start: ThreadDetail[] = THREADS, { delay = 300, checkMs = 4000 } = {}): ThreadsApi {
  const all = new Map(start.map((d) => [d.id, structuredClone(d)]));
  const find = (id: string) => {
    const d = all.get(id);
    if (!d) throw new Error("404: нет такого треда");
    return d;
  };
  const out = (d: ThreadDetail): Thread => { const { previous: _, ...rest } = structuredClone(d); return { ...rest, messages_count: d.messages.length }; };
  const finish = (d: ThreadDetail, state: Thread["state"]) =>
    Object.assign(d, { state, closed_at: new Date().toISOString(), waiting_for: null, waiting_for_you: false });
  let n = 100;
  const checked = new Set<string>();
  const check = (d: ThreadDetail) => {
    if (checked.has(d.id)) return;
    checked.add(d.id);
    setTimeout(() => {
      d.messages.push({ ...analyzerYes, id: `m${n++}`, created_at: new Date().toISOString() });
      finish(d, "resolved");
      checked.delete(d.id);
    }, checkMs);
  };
  // A thread that is checking when first read is checked from then on (not from the import)
  const kick = () => { for (const d of all.values()) if (d.state === "checking") check(d); };
  const mine = (text: string) => message({ id: `m${n++}`, author_label: "Олег", role: "designer", text, created_at: new Date().toISOString(), mine: true });
  return {
    async list() { kick(); await wait(delay); return listOf([...all.values()]); },
    async get(_key, id) { kick(); await wait(delay); return structuredClone(find(id)); },
    async send(_key, id, text) {
      await wait(delay);
      const d = find(id);
      if (d.state !== "open") throw new Error("409: тред закрыт для сообщений");
      d.messages.push(mine(text));
      return out(d);
    },
    async accept(_key, id, messageId) {
      await wait(delay);
      const d = find(id);
      Object.assign(d, { state: "checking", accepted_message_id: messageId, waiting_for: null, waiting_for_you: false });
      d.messages = d.messages.map((m) => ({ ...m, accepted: m.id === messageId }));
      check(d);
      return out(d);
    },
    async close(_key, id, comment) {
      await wait(delay);
      const d = find(id);
      if (comment) d.messages.push(mine(comment));
      finish(d, "closed");
      return out(d);
    },
  };
}
