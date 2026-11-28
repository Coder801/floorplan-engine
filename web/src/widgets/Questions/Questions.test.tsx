import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AnswerRefused, type AnswerResult } from "@/shared/api";
import type { QuestionsMemory } from "@/shared/questions";
import { fail, stubApi } from "@/shared/testApi";
import { project, question } from "@/shared/testData";
import type { Project } from "@/shared/types";
import { ask, listOf, thread } from "@/widgets/Threads/mock";
import { Questions } from "./index";

const done: AnswerResult = { built: true, rebuilt: false };

function setup(p: Project, over: Partial<Parameters<typeof Questions>[0]> = {}) {
  const props = {
    project: p, busy: false,
    onAnswer: vi.fn().mockResolvedValue(done), onReview: vi.fn().mockResolvedValue(done),
    stages: ["plan", "electrical", "panel"], onShow: vi.fn(),
    memory: { current: { drafts: {} } as QuestionsMemory },
    ...over,
  };
  const view = render(<Questions {...props} />);
  return { ...props, ...view, rerender: (more: Partial<typeof props>) => view.rerender(<Questions {...props} {...more} />) };
}

const withQuestions = (qs: ReturnType<typeof question>[], over: Partial<Project> = {}) =>
  project({ report: { questions: qs, issues: [] }, ...over });

describe("Questions", () => {
  it("says when there is no report or no questions", () => {
    const { rerender } = setup(project({ report: null }));
    expect(screen.getByText("Отчёта нет — проект не собран")).toBeInTheDocument();
    rerender({ project: project() });
    expect(screen.getByText("Вопросов нет")).toBeInTheDocument();
  });

  it("opens the first open question; a number is saved, a non-number is refused in place", async () => {
    const user = userEvent.setup();
    const { onAnswer } = setup(withQuestions([question()]));
    expect(screen.getByText("Сейчас в проекте: 2700 мм")).toBeInTheDocument();
    const field = screen.getByRole("textbox", { name: "Ваш ответ" });
    await user.type(field, "abc");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Нужно число");
    expect(onAnswer).not.toHaveBeenCalled();
    await user.clear(field);
    await user.type(field, "2 750,5");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(onAnswer).toHaveBeenCalledWith("q1", 2750.5);
  });

  it("keeps the assumption by one button", async () => {
    const { onAnswer } = setup(withQuestions([question()]));
    await userEvent.click(screen.getByRole("button", { name: "Оставить 2700 мм" }));
    expect(onAnswer).toHaveBeenCalledWith("q1", { accept: true });
  });

  it("a choice is a radio group with the person's words; the assumption is kept, not written", async () => {
    const user = userEvent.setup();
    const choice = withQuestions([question({
      answer: "choice", options: ["none", "ups"], option_labels: { none: "Без резерва", ups: "ИБП" }, assumption: "none", unit: undefined,
    })]);
    const first = setup(choice);
    const group = screen.getByRole("radiogroup", { name: "Ваш ответ" });
    expect(within(group).getByRole("radio", { name: /Без резерва.*сейчас/ })).toBeInTheDocument();
    await user.click(within(group).getByRole("radio", { name: /ИБП/ }));
    expect(first.onAnswer).toHaveBeenCalledWith("q1", "ups");
    first.unmount();
    const second = setup(choice);
    await user.click(screen.getByRole("radio", { name: /Без резерва/ }));
    expect(second.onAnswer).toHaveBeenCalledWith("q1", { accept: true });
  });

  it("a text answer waits for text and goes as { text }", async () => {
    const user = userEvent.setup();
    const { onAnswer } = setup(withQuestions([question({ answer: "text", assumption: undefined, unit: undefined })]));
    const send = screen.getByRole("button", { name: "Отправить ответ" });
    expect(send).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Ваш ответ" }), "  у окна  ");
    await user.click(send);
    expect(onAnswer).toHaveBeenCalledWith("q1", { text: "у окна" });
  });

  it("without the right to answer it only reads", async () => {
    setup(withQuestions([question()], { can: { choose_variant: false, answer: false, review: false } }));
    expect(screen.getByText("Только просмотр: отвечать может студия или заказчик.")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Какая высота потолка/ }));
    expect(screen.getByText("Ответа пока нет")).toBeInTheDocument();
    // the studio-only details are hidden too
    expect(screen.queryByText("room.yaml: ceiling_height")).toBeNull();
  });

  it("shows a refusal of the check and leads to the answer in its way", async () => {
    const user = userEvent.setup();
    const refused = new AnswerRefused(
      [{ file: "room.yaml", path: "walls.w2", message: "Контур не замкнулся: ΔX 100 мм" }],
      [{ id: "q2", text: "Длина стены w2" }],
    );
    const { onAnswer } = setup(withQuestions([question(), question({ id: "q2", text: "Длина стены w2" })], {
      answers: { q2: 4000 },
    }), { onAnswer: vi.fn().mockRejectedValue(refused) });
    await user.type(screen.getByRole("textbox", { name: "Ваш ответ" }), "3000");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Не сохранено. Проект остался как был.");
    expect(alert).toHaveTextContent("Контур не замкнулся");
    expect(alert).toHaveTextContent("room.yaml: walls.w2");
    expect(onAnswer).toHaveBeenCalledOnce();
    await user.click(within(alert).getByRole("button", { name: "Длина стены w2" }));
    expect(screen.getByText("Ответ: 4000 мм")).toBeInTheDocument();
  });

  it("a rebuilding answer shows the band, moves to the next question and reports the result", async () => {
    const user = userEvent.setup();
    const onAnswer = vi.fn().mockResolvedValue({ built: true, rebuilt: true });
    const qs = [question(), question({ id: "q2", text: "Где щит?", answer: "text", assumption: undefined })];
    const view = setup(withQuestions(qs), { onAnswer });
    await user.click(screen.getByRole("button", { name: "Оставить 2700 мм" }));
    expect(screen.getByRole("status")).toHaveTextContent("Пересобираю проект…");
    expect(screen.getByRole("textbox", { name: "Ваш ответ" })).toBeInTheDocument();  // q2 is open now
    view.rerender({ busy: true });
    view.rerender({ busy: false, project: withQuestions(qs.slice(1), { answers: {} }) });
    expect(await screen.findByText("Готово, листы обновлены.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Вопросов стало меньше на 1");
    await user.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("closed questions fold away; an answer can be changed or removed", async () => {
    const user = userEvent.setup();
    const { onAnswer } = setup(withQuestions([question()], { answers: { q1: 2800 } }));
    expect(screen.queryByText("Какая высота потолка?")).toBeNull();
    const fold = screen.getByRole("button", { name: /Закрыты · 1/ });
    expect(fold).toHaveAttribute("aria-expanded", "false");
    await user.click(fold);
    await user.click(screen.getByRole("button", { name: /Какая высота потолка/ }));
    expect(screen.getByText("Ответ: 2800 мм")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Изменить" }));
    expect(screen.getByRole("textbox", { name: "Ваш ответ" })).toHaveValue("2800");
    await user.click(screen.getByRole("button", { name: "Отмена" }));
    await user.click(screen.getByRole("button", { name: "Снять ответ" }));
    expect(onAnswer).toHaveBeenCalledWith("q1", null);
  });

  it("removing a text answer asks first", async () => {
    const user = userEvent.setup();
    const { onAnswer } = setup(withQuestions([question({ answer: "text" })], { answers: { q1: { text: "у окна" } } }));
    await user.click(screen.getByRole("button", { name: /Какая высота потолка/ }));
    await user.click(screen.getByRole("button", { name: "Снять ответ" }));
    expect(screen.getByText("Снять ответ? Текст будет удалён.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Нет" }));
    expect(onAnswer).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Снять ответ" }));
    await user.click(screen.getByRole("button", { name: "Да, снять" }));
    expect(onAnswer).toHaveBeenCalledWith("q1", null);
  });

  it("the studio takes a client answer into account or sends it back with a comment", async () => {
    const user = userEvent.setup();
    const clientQ = question({ audience: "client", answer: "text", assumption: undefined, text: "Где будет телевизор?" });
    const { onReview } = setup(withQuestions([clientQ], { answers: { q1: { text: "у окна" } } }));
    await user.click(screen.getByRole("button", { name: /Где будет телевизор/ }));
    expect(screen.getByRole("button", { name: /заказчику/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Учтено" }));
    expect(onReview).toHaveBeenLastCalledWith("q1", "resolve", undefined);
    await user.click(screen.getByRole("button", { name: "Вернуть" }));
    const send = screen.getByRole("button", { name: "Вернуть с комментарием" });
    expect(send).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Что уточнить" }), "Какая стена?");
    await user.click(send);
    expect(onReview).toHaveBeenLastCalledWith("q1", "return", "Какая стена?");
  });

  it("a sent-back answer is open again with the studio's comment", () => {
    setup(withQuestions([question({ audience: "client", answer: "text" })], {
      answers: { q1: { text: "у окна", returned: "Какая стена?" } },
    }));
    expect(screen.getByText("Студия просит уточнить: Какая стена?")).toBeInTheDocument();
  });

  it("leads to the object on the drawing", async () => {
    const { onShow } = setup(withQuestions([question({ stage: "panel", target: undefined })]));
    await userEvent.click(screen.getByRole("button", { name: "Открыть щит" }));
    expect(onShow).toHaveBeenCalledWith({ stage: "panel", key: null });
  });

  it("keeps the typed text and the open question in memory when the panel closes", async () => {
    const memory = { current: { drafts: {} } as QuestionsMemory };
    const first = setup(withQuestions([question()]), { memory });
    await userEvent.type(screen.getByRole("textbox", { name: "Ваш ответ" }), "2650");
    first.unmount();
    setup(withQuestions([question()]), { memory });
    expect(screen.getByRole("textbox", { name: "Ваш ответ" })).toHaveValue("2650");
  });

  it("a question to the installer clarifies, as the client's", async () => {
    setup(withQuestions([question({ audience: "installer", answer: "text" })], { answers: { q1: { text: "у окна" } } }));
    await userEvent.click(screen.getByRole("button", { name: /монтажнику/ }));
    expect(screen.getByRole("button", { name: "Учтено" })).toBeInTheDocument();
  });

  describe("the database viewer: threads", () => {
    const T = "/api/projects/p1/threads";
    const formThread = thread({
      id: "t7", messages: [],
      question: ask({ text: "Какая высота потолка?", audience: "studio", kind: "value", stage: "plan" }),
    });

    it("threads instead of the list; a studio value keeps its form above the feed", async () => {
      stubApi({ [`GET ${T}`]: listOf([formThread]), [`GET ${T}/t7`]: formThread });
      const user = userEvent.setup();
      const { onAnswer } = setup(withQuestions([question()], { id: "p1", work: true }));
      await user.click(await screen.findByRole("button", { name: /Какая высота потолка/ }));
      expect(screen.getByText("Сейчас в проекте: 2700 мм")).toBeInTheDocument();
      await user.type(screen.getByRole("textbox", { name: "Ваш ответ" }), "2750");
      await user.click(screen.getByRole("button", { name: "Сохранить" }));
      expect(onAnswer).toHaveBeenCalledWith("q1", 2750);
      expect(await screen.findByRole("textbox", { name: "Сообщение" })).toBeInTheDocument();  // the feed under it
      // the old "taken into account / send back" is not there
      expect(screen.queryByRole("button", { name: "Учтено" })).toBeNull();
    });

    it("a text question has no answer form: the reply is a message", async () => {
      const text = thread({ id: "t1", question: ask({ text: "Где щит?", audience: "studio" }) });
      stubApi({ [`GET ${T}`]: listOf([text]), [`GET ${T}/t1`]: text });
      setup(withQuestions([question({ answer: "text", text: "Где щит?" })], { id: "p1", work: true }));
      await userEvent.click(await screen.findByRole("button", { name: /Где щит/ }));
      expect(await screen.findByRole("textbox", { name: "Сообщение" })).toBeInTheDocument();
      expect(screen.queryByRole("textbox", { name: "Ваш ответ" })).toBeNull();
      expect(screen.queryByRole("button", { name: "Отправить ответ" })).toBeNull();
    });

    it("a client question of any kind is answered by a message, not by POST …/answers", async () => {
      const client = thread({ id: "t2", question: ask({ id: "q1", text: "Какая высота потолка?", kind: "value", audience: "client" }) });
      const sent = stubApi({ [`GET ${T}`]: listOf([client]), [`GET ${T}/t2`]: client });
      setup(withQuestions([question({ audience: "client" })], { id: "p1", work: true }));
      await userEvent.click(await screen.findByRole("button", { name: /Какая высота потолка/ }));
      expect(await screen.findByRole("textbox", { name: "Сообщение" })).toBeInTheDocument();
      expect(screen.queryByRole("textbox", { name: "Ваш ответ" })).toBeNull();
      expect(screen.queryByRole("button", { name: /Оставить/ })).toBeNull();
      expect(sent.every((s) => s.method === "GET")).toBe(true);
    });

    it("a server without threads (404) keeps answers.yaml", async () => {
      stubApi({ [`GET ${T}`]: fail(404, "Not Found") });
      setup(withQuestions([question()], { id: "p1", work: true }));
      expect(await screen.findByText("Сейчас в проекте: 2700 мм")).toBeInTheDocument();
      expect(screen.getByText("нужен ответ")).toBeInTheDocument();
    });

    it("the folder viewer (no work) never asks for threads", () => {
      const sent = stubApi({});
      setup(withQuestions([question()], { work: false }));
      expect(screen.getByRole("textbox", { name: "Ваш ответ" })).toBeInTheDocument();
      expect(sent).toEqual([]);
    });
  });
});
