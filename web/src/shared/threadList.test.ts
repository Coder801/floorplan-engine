import { describe, expect, it } from "vitest";
import {
  acceptable, acceptedIn, answeredByForm, audienceOf, firstTab, lastWords, rightsOf, tabCounts, threadOrder,
} from "./threadList";
import type { Thread, ThreadMessage } from "./threads";

const message = (over: Partial<ThreadMessage> = {}): ThreadMessage => ({
  id: "m", author: "user", author_label: "", role: "client", text: "т", meta: {}, created_at: "2026-11-28T10:00:00Z",
  mine: false, accepted: false, ...over,
});
const thread = (over: Partial<Thread> = {}): Thread => ({
  id: "t", state: "open", created_at: "2026-11-28T09:00:00Z", closed_at: null, previous_thread_id: null, chain: 1,
  accepted_message_id: null, result_version: null, messages_count: 1, messages: [message()], waiting_for: "studio", waiting_for_you: true,
  question: {
    id: "q1", text: "?", stage: "plan", audience: "client", kind: "text", severity: "major", assumption: null, target: null,
    unit: null, options: [], option_labels: {}, source: "analyzer", in_intake: true,
  },
  ...over,
});

const live = (id: string, waiting: boolean, audience: "client" | "installer" = "client", severity = "major") =>
  thread({ id, waiting_for_you: waiting, question: { ...thread().question!, audience, severity } });

describe("вкладки и порядок", () => {
  const list = [
    live("a", false),
    live("b", true),
    live("c", false, "installer", "critical"),
    thread({ id: "d", state: "resolved", closed_at: "2026-11-28T12:00:00Z", waiting_for_you: false }),
    thread({ id: "e", state: "closed", closed_at: "2026-11-28T13:00:00Z", waiting_for_you: false }),
  ];

  it("что ждёт вас — наверху, законченные — новые первыми", () => {
    expect(threadOrder(list.filter((x) => audienceOf(x) === "client")).map((x) => x.id)).toEqual(["b", "a", "e", "d"]);
  });

  it("счётчики по адресатам — по waiting_for_you сервера; открывается вкладка, где ждут", () => {
    const counts = tabCounts(list);
    expect(counts).toEqual([
      { audience: "client", total: 4, live: 2, waiting: 1 },
      { audience: "installer", total: 1, live: 1, waiting: 0 },
      { audience: "studio", total: 0, live: 0, waiting: 0 },
    ]);
    expect(firstTab(counts)).toBe("client");
    expect(firstTab(tabCounts([list[2]]))).toBe("installer");
    expect(firstTab(tabCounts([]))).toBe("client");
    expect(audienceOf(thread({ question: null }))).toBe("studio");  // a free thread
  });
});

describe("права в треде", () => {
  const STUDIO = { answer: true, review: true };
  it("только открытый тред: писать — с answer или review; принять и закрыть — студия", () => {
    expect(rightsOf(thread(), STUDIO)).toEqual({ write: true, accept: true, close: true });
    expect(rightsOf(thread(), { answer: true, review: false })).toEqual({ write: true, accept: false, close: false });
    expect(rightsOf(thread(), { answer: false, review: false })).toEqual({ write: false, accept: false, close: false });
    const none = { write: false, accept: false, close: false };
    for (const state of ["checking", "resolved", "superseded", "closed"] as const) expect(rightsOf(thread({ state }), STUDIO)).toEqual(none);
  });

  it("принять нельзя только у вопроса студии с формой; у заказчика и монтажника — любой вид", () => {
    const q = thread().question!;
    expect(rightsOf(thread({ question: { ...q, kind: "value", audience: "studio" } }), STUDIO)).toEqual({ write: true, accept: false, close: true });
    expect(rightsOf(thread({ question: { ...q, kind: "choice", audience: "client" } }), STUDIO).accept).toBe(true);
    expect(rightsOf(thread({ question: { ...q, kind: "value", audience: "installer" } }), STUDIO).accept).toBe(true);
    expect(rightsOf(thread({ question: { ...q, kind: "text", audience: "studio" } }), STUDIO).accept).toBe(true);
  });

  it("принять можно сообщение человека с текстом", () => {
    expect(acceptable(message())).toBe(true);
    expect(acceptable(message({ text: " " }))).toBe(false);
    expect(acceptable(message({ author: "analyzer" }))).toBe(false);
  });

  it("формой — число, выбор и группы вопроса студии", () => {
    expect(answeredByForm("value", "studio")).toBe(true);
    expect(answeredByForm("groups", undefined)).toBe(true);  // an older build: the studio's
    expect(answeredByForm("choice", "studio")).toBe(true);
    expect(answeredByForm("choice", "client")).toBe(false);
    expect(answeredByForm("value", "installer")).toBe(false);
    expect(answeredByForm("text", "studio")).toBe(false);
    expect(answeredByForm(undefined, "studio")).toBe(false);
  });

  it("свёрнутая строка — последнее сообщение с текстом; цитата — принятое в прошлом треде", () => {
    expect(lastWords(thread({ messages: [message({ text: "первое" }), message({ author: "analyzer", text: "" })] }))?.text).toBe("первое");
    expect(lastWords(thread({ messages: [] }))).toBeNull();
    expect(acceptedIn(thread({ messages: [message({ id: "x" }), message({ id: "y", accepted: true })] }))?.id).toBe("y");
    expect(acceptedIn(thread({ accepted_message_id: "x", messages: [message({ id: "x" })] }))?.id).toBe("x");
    expect(acceptedIn(undefined)).toBeNull();
  });
});
