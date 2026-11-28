import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { QuestionsMemory } from "@/shared/questions";
import { fail, stubApi } from "@/shared/testApi";
import { project } from "@/shared/testData";
import { POLL_MS } from "@/shared/threadList";
import type { Project } from "@/shared/types";
import { Threads } from "./index";
import { listOf, thread, THREADS } from "./mock";

const T = "/api/projects/p1/threads";
const STUDIO = project({ id: "p1", work: true });
const CLIENT = project({ id: "p1", work: true, can: { choose_variant: true, answer: true, review: false } });

function setup(p: Project, over: Partial<Parameters<typeof Threads>[0]> = {}) {
  const props = {
    project: p, extraFor: () => null, drafts: {}, onDraft: vi.fn(),
    memory: { current: { drafts: {} } as QuestionsMemory }, onUnavailable: vi.fn(), onSettled: vi.fn(), ...over,
  };
  return { ...props, ...render(<Threads {...props} />) };
}

describe("Threads", () => {
  afterEach(() => vi.useRealTimers());

  it("the studio: tabs by audience, a dot where it decides, the chain and the states", async () => {
    stubApi({ [`GET ${T}`]: listOf(THREADS) });
    const user = userEvent.setup();
    setup(STUDIO);
    const tabs = await screen.findByRole("tablist", { name: "Кому вопрос" });
    expect(within(tabs).getAllByRole("tab").map((x) => x.textContent)).toEqual(["Заказчику3", "Монтажнику", "Студии1"]);
    // waiting_for_you of the server: t1 (client tab) and t7 (studio tab)
    expect(screen.getByRole("tab", { name: "Заказчику: ждут вашего решения — 1" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("ждут вашего решения")).toBeInTheDocument();
    const first = screen.getByRole("button", { name: /Где будет телевизор в гостиной/ });
    expect(first).toHaveTextContent("ждёт вас");
    const followUp = screen.getByRole("button", { name: /Какая ширина проёма в кухню, мм/ });
    expect(followUp).toHaveTextContent("2-й тред по вопросу");
    expect(followUp).toHaveTextContent("ждём ответа");  // waiting_for: client
    expect(screen.getByRole("button", { name: /Нужна ли розетка/ })).toHaveTextContent("проверяется");
    // finished ones fold away
    await user.click(screen.getByRole("button", { name: /Закрыты · 2/ }));
    expect(screen.getByRole("button", { name: /Какая ширина проёма в кухню\?/ })).toHaveTextContent("не решён");
    await user.click(screen.getByRole("tab", { name: "Монтажнику" }));
    expect(screen.queryByRole("button", { name: /телевизор/ })).toBeNull();
  });

  it("the client: one list without tabs, the count of what waits for its reply", async () => {
    const mine = thread({ id: "c1", messages: [], waiting_for: "client", waiting_for_you: true });
    stubApi({ [`GET ${T}`]: listOf([mine]), [`GET ${T}/c1`]: mine });
    setup(CLIENT);
    expect(await screen.findByText("ждут вашего ответа")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).toBeNull();
    const row = screen.getByRole("button", { name: /Где будет телевизор/ });
    expect(row).toHaveTextContent("ждёт вас");
    await userEvent.click(row);
    expect(await screen.findByRole("textbox", { name: "Сообщение" })).toBeInTheDocument();
  });

  it("the question panel adds its form above the feed of an opened thread", async () => {
    const q = THREADS.find((d) => d.id === "t7")!;
    stubApi({ [`GET ${T}`]: listOf([q]), [`GET ${T}/t7`]: q });
    const extraFor = vi.fn((qid: string) => <div>{`форма ${qid}`}</div>);
    setup(STUDIO, { extraFor });
    await userEvent.click(await screen.findByRole("button", { name: /Высота потолка в коридоре/ }));
    expect(screen.getByText("форма q6")).toBeInTheDocument();
  });

  it("no threads on the server (404) — back to answers.yaml", async () => {
    stubApi({ [`GET ${T}`]: fail(404, "Not Found") });
    const { onUnavailable } = setup(STUDIO);
    await vi.waitFor(() => expect(onUnavailable).toHaveBeenCalledOnce());
  });

  it("another refusal says so and can be retried", async () => {
    let n = 0;
    stubApi({ [`GET ${T}`]: () => (n++ ? listOf([]) : fail(500, "упал")) });
    setup(STUDIO);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить вопросы: упал");
    await userEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("Вопросов нет")).toBeInTheDocument();
  });

  it("a thread checked with its card closed: the list is polled, its end reads the project again", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const checking = THREADS.find((d) => d.state === "checking")!;
    let rows = [checking];
    const sent = stubApi({ [`GET ${T}`]: () => listOf(rows) });
    const { onSettled } = setup(STUDIO);
    expect(await screen.findByText("проверяется")).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS); });
    expect(sent).toHaveLength(2);
    expect(onSettled).not.toHaveBeenCalled();
    rows = [{ ...rows[0], state: "resolved" }];
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS); });
    expect(onSettled).toHaveBeenCalledOnce();
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS * 2); });
    expect(sent).toHaveLength(3);
  });

  it("the open thread and the tab outlive the panel", async () => {
    const open = THREADS.find((d) => d.id === "t6")!;  // the installer's
    stubApi({ [`GET ${T}`]: listOf(THREADS), [`GET ${T}/t6`]: open });
    const memory = { current: { drafts: {}, thread: "t6", tab: "installer" } as QuestionsMemory };
    setup(STUDIO, { memory });
    expect(await screen.findByRole("tab", { name: "Монтажнику" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("Перенесли в ванную, исходники поправлены.")).toBeInTheDocument();
  });
});
