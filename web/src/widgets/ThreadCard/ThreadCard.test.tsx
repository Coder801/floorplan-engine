import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fail, stubApi } from "@/shared/testApi";
import { POLL_MS } from "@/shared/threadList";
import type { ThreadDetail } from "@/shared/threads";
import type { Project } from "@/shared/types";
import { ask, message, summaryOf, thread, THREADS } from "@/widgets/Threads/mock";
import { ThreadCard } from "./index";

const T = "/api/projects/kv42/threads";
const STUDIO: Project["can"] = { choose_variant: true, answer: true, review: true };
const CLIENT: Project["can"] = { choose_variant: true, answer: true, review: false };
const VIEWER: Project["can"] = { choose_variant: false, answer: false, review: false };

function setup(d: ThreadDetail, can: Project["can"], over: Partial<Parameters<typeof ThreadCard>[0]> = {}) {
  const props = {
    projectKey: "kv42", summary: summaryOf(d), can, draft: "", onDraft: vi.fn(), onChanged: vi.fn(), onOpen: vi.fn(), ...over,
  };
  const view = render(<ThreadCard {...props} />);
  return { ...props, ...view };
}

describe("ThreadCard", () => {
  afterEach(() => vi.useRealTimers());

  it("the feed: people, the AI check with its reason and changes, the accepted answer", async () => {
    const resolved = THREADS.find((d) => d.state === "resolved")!;
    stubApi({ [`GET ${T}/t3`]: resolved });
    setup(resolved, STUDIO);
    expect(await screen.findByText("1100 мм от пола, по центру стены.")).toBeInTheDocument();
    expect(screen.getByText("Иван · заказчик")).toBeInTheDocument();
    expect(screen.getByText("Проверка ИИ")).toBeInTheDocument();
    expect(screen.getByText("ответ закрывает вопрос")).toBeInTheDocument();
    expect(screen.getByText("ответ даёт место и высоту ТВ")).toBeInTheDocument();
    expect(screen.getByText("electrical.yaml: points.tv1.height 1100")).toBeInTheDocument();
    expect(screen.getByText("✓ принят как ответ")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Ответ закрыл вопрос");
    // a finished thread only reads, for the studio too
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Принять как ответ" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Закрыть тред" })).toBeNull();
  });

  it("the client writes but neither accepts nor closes; a viewer only reads", async () => {
    const open = thread();
    stubApi({ [`GET ${T}/t1`]: open });
    const first = setup(open, CLIENT, { draft: "у окна" });
    expect(await screen.findByRole("textbox", { name: "Сообщение" })).toHaveValue("у окна");
    expect(screen.queryByRole("button", { name: "Принять как ответ" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Закрыть тред" })).toBeNull();
    first.unmount();
    setup(open, VIEWER);
    expect(await screen.findByText("Телевизор — на стене напротив дивана.")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("a reply is sent, the thread from the answer replaces the card, the list told", async () => {
    const open = thread();
    const after = summaryOf(thread({ messages: [...open.messages, message({ id: "m2", text: "на стене у окна", mine: true })] }));
    const sent = stubApi({ [`GET ${T}/t1`]: open, [`POST ${T}/t1/messages`]: after });
    const { onDraft, onChanged } = setup(open, CLIENT, { draft: "  на стене у окна  " });
    await userEvent.click(await screen.findByRole("button", { name: "Отправить" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
    expect(sent.find((s) => s.method === "POST")?.body).toEqual({ text: "на стене у окна" });
    expect(sent.filter((s) => s.method === "GET")).toHaveLength(1);
    // the draft is the parent's (onDraft): the field still holds it here, the feed has the message
    expect(within(screen.getByRole("list")).getByText("на стене у окна")).toBeInTheDocument();
    expect(screen.getByText("Иван · заказчик · вы")).toBeInTheDocument();
    expect(onDraft).toHaveBeenCalledWith("");
  });

  it("accept → checking with an indicator → polled until the check ends", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    let state: ThreadDetail = thread();
    const sent = stubApi({
      [`GET ${T}/t1`]: () => state,
      [`POST ${T}/t1/accept`]: (body: unknown) => {
        state = { ...state, state: "checking", accepted_message_id: (body as { message_id: string }).message_id };
        return summaryOf(state);
      },
    });
    const { onChanged } = setup(state, STUDIO);
    await user.click(await screen.findByRole("button", { name: "Принять как ответ" }));
    expect(sent.find((s) => s.method === "POST")).toMatchObject({ path: `${T}/t1/accept`, body: { message_id: "m1" } });
    expect(await screen.findByText("ИИ проверяет принятый ответ…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Закрыть тред" })).toBeNull();  // not while it is checked
    expect(screen.queryByRole("textbox")).toBeNull();  // no replies either
    expect(onChanged).toHaveBeenCalledTimes(1);
    const reads = () => sent.filter((s) => s.method === "GET").length;
    const before = reads();
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS); });
    expect(reads()).toBe(before + 1);  // still checking: asked again
    state = { ...state, state: "resolved", messages: [...state.messages, message({ id: "m9", author: "analyzer", text: "", meta: { verdict: "satisfied", reason: "годится" } })] };
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS); });
    expect(await screen.findByText("годится")).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalledTimes(2);  // the check ended: the list and the project
    const after = reads();
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS * 3); });
    expect(reads()).toBe(after);  // no more polling
  });

  it("a refusal of the server shows its text", async () => {
    const open = thread();
    stubApi({ [`GET ${T}/t1`]: open, [`POST ${T}/t1/accept`]: fail(409, "Тред уже проверяется") });
    setup(open, STUDIO);
    await userEvent.click(await screen.findByRole("button", { name: "Принять как ответ" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Тред уже проверяется");
  });

  it("the studio closes a thread with an optional comment", async () => {
    const open = thread();
    const sent = stubApi({ [`GET ${T}/t1`]: open, [`POST ${T}/t1/close`]: summaryOf(thread({ state: "closed" })) });
    const user = userEvent.setup();
    setup(open, STUDIO);
    await user.click(await screen.findByRole("button", { name: "Закрыть тред" }));
    await user.type(screen.getByRole("textbox", { name: "Почему закрываете (необязательно)" }), "решено правкой");
    await user.click(screen.getByRole("button", { name: "Закрыть" }));
    await waitFor(() => expect(sent.find((s) => s.method === "POST")?.body).toEqual({ comment: "решено правкой" }));
  });

  it("a follow-up links to the previous thread and quotes the answer accepted there", async () => {
    const next = THREADS.find((d) => d.id === "t5")!;
    stubApi({ [`GET ${T}/t5`]: next });
    const { onOpen } = setup(next, STUDIO);
    expect(await screen.findByText("«Как на кухне.»")).toBeInTheDocument();
    expect(screen.getByText("Принятый ответ в прошлом треде")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "← Предыдущий тред" }));
    expect(onOpen).toHaveBeenCalledWith("t4");
  });

  it("a studio question answered by a form: its messages are not accepted", async () => {
    const form = thread({ question: ask({ kind: "value", audience: "studio" }) });
    stubApi({ [`GET ${T}/t1`]: form });
    setup(form, STUDIO);
    expect(await screen.findByRole("textbox", { name: "Сообщение" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Принять как ответ" })).toBeNull();
    expect(screen.getByRole("button", { name: "Закрыть тред" })).toBeInTheDocument();
  });

  it("a client choice: options fill the reply, the studio accepts the message", async () => {
    const choice = thread({ question: ask({ kind: "choice", options: ["none", "ups"], option_labels: { none: "Без резерва", ups: "ИБП" } }) });
    stubApi({ [`GET ${T}/t1`]: choice });
    const first = setup(choice, CLIENT);
    const group = await screen.findByRole("group", { name: "Варианты ответа" });
    await userEvent.click(within(group).getByRole("button", { name: "ИБП" }));
    expect(first.onDraft).toHaveBeenCalledWith("ИБП");
    first.unmount();
    setup(choice, STUDIO);
    expect(await screen.findByRole("button", { name: "Принять как ответ" })).toBeInTheDocument();
  });
});
