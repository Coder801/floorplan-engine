import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fail, stubApi } from "@/shared/testApi";
import type { WorkCan, WorkState, WorkTask } from "@/shared/types";
import type { WorkRun } from "@/shared/work";
import { CLIENT, INSTALLER, STUDIO, TASKS, draftState, workState } from "@/widgets/WorkStage/mock";
import { WorkCard } from "./index";

const W = "/api/projects/p1/work";
const task = (id: string) => TASKS.find((t) => t.id === id)!;
// The card's tabs under the top: "Work" is open by default
const tab = (name: RegExp) => userEvent.click(screen.getByRole("tab", { name }));
const ask = vi.fn(() => true);
beforeEach(() => { ask.mockReset().mockReturnValue(true); vi.stubGlobal("confirm", ask); });

// A run that sends the call to the stubbed API and says whether it went through, like useWork
const live = (): WorkRun => vi.fn(async (call) => { try { await call("p1"); return true; } catch { return false; } });

function open(t: WorkTask, can: WorkCan, over: Partial<Parameters<typeof WorkCard>[0]> & { state?: WorkState } = {}) {
  const props = {
    task: t, state: workState({ can }), run: live(), busy: false, error: null, onError: vi.fn(), me: "u-petro",
    onClose: vi.fn(), onOpen: vi.fn(), ...over,
  };
  return { ...props, ...render(<WorkCard {...props} />) };
}

describe("WorkCard", () => {
  it("the installer hands in a returned task, ticks the criterion, writes the fact and a comment", async () => {
    const user = userEvent.setup();
    const sent = stubApi({
      [`POST ${W}/tasks/cable/status`]: workState(), [`PATCH ${W}/tasks/cable/checks`]: workState(),
      [`PATCH ${W}/tasks/cable/lines/l4`]: workState(), [`POST ${W}/tasks/cable/comments`]: workState(),
    });
    open(task("cable"), INSTALLER);
    expect(screen.getByRole("dialog", { name: "Прокладка кабеля" })).toBeInTheDocument();
    expect(screen.getByText("Возвращено")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Сдать" }));
    expect(sent.at(-1)?.body).toEqual({ to: "review" });

    const criterion = screen.getByRole("checkbox", { name: "концы промаркированы" });
    expect(criterion).not.toBeChecked();
    await user.click(criterion);
    expect(criterion).toBeChecked();
    expect(sent.at(-1)?.body).toEqual({ index: 1, checked: true });

    await tab(/Позиции/);
    const fact = screen.getByRole("textbox", { name: "Факт: Прокладка кабеля" });
    expect(fact).toHaveValue("615");
    await user.clear(fact);
    await user.type(fact, "620,5{Enter}");
    expect(sent.at(-1)).toMatchObject({ method: "PATCH", body: { fact_qty: 620.5 } });
    // no prices for the installer
    expect(screen.queryByRole("textbox", { name: /^Цена:/ })).toBeNull();

    await tab(/Лента/);
    expect(screen.getByText("В спальне кабель к бра не закреплён, на фото не видно маркировку.")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Комментарий" }), "Закрепил");
    await user.click(screen.getByRole("button", { name: "Отправить" }));
    expect(sent.at(-1)?.body).toEqual({ text: "Закрепил" });
  });

  it("a ticked point goes back when the server refuses it", async () => {
    const user = userEvent.setup();
    stubApi({ [`PATCH ${W}/tasks/cable/checks`]: fail(409, "план закрыт") });
    open(task("cable"), INSTALLER);
    const criterion = screen.getByRole("checkbox", { name: "концы промаркированы" });
    await user.click(criterion);
    await vi.waitFor(() => expect(criterion).not.toBeChecked());
  });

  it("an installer cannot start a task that waits for others, nor hand in one without its photo", () => {
    const { unmount } = open({ ...task("insulation") }, INSTALLER);
    const take = screen.getByRole("button", { name: "Взять в работу" });
    expect(take).toBeDisabled();
    expect(take).toHaveAccessibleDescription("Ждёт: Прокладка кабеля, Распаечные коробки. Начать раньше может только студия.");
    unmount();
    open({ ...task("insulation"), status: "in_progress", waiting: [] }, INSTALLER);
    expect(screen.getByRole("button", { name: "Сдать" })).toHaveAccessibleDescription("Сначала добавьте фото: без него задачу не сдать.");
  });

  it("the studio accepts for the client after saying how the client confirmed", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ [`POST ${W}/tasks/boxes/status`]: workState() });
    open(task("boxes"), STUDIO);
    expect(screen.getByText("Примите работу")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Принять" }));
    expect(sent).toHaveLength(0);
    await user.click(screen.getByRole("radio", { name: "По звонку" }));
    await user.click(screen.getByRole("button", { name: "Подтвердить за заказчика" }));
    expect(sent[0].body).toEqual({ to: "accepted", on_behalf: "phone" });
  });

  it("returning asks what to fix first", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ [`POST ${W}/tasks/boxes/status`]: workState() });
    open(task("boxes"), CLIENT, { me: null });
    await user.click(screen.getByRole("button", { name: "Вернуть" }));
    const send = screen.getByRole("button", { name: "Вернуть с комментарием" });
    expect(send).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Что исправить" }), "Нет крышек");
    await user.click(send);
    expect(sent[0].body).toEqual({ to: "returned", comment: "Нет крышек" });  // the client: no channel
  });

  it("the studio edits an extra task while its money is open", async () => {
    const user = userEvent.setup();
    const sent = stubApi({
      [`PATCH ${W}/tasks/niche`]: workState(), [`PATCH ${W}/tasks/niche/lines/l14`]: workState(),
      [`POST ${W}/tasks/niche/lines`]: workState(),
    });
    open(task("niche"), STUDIO);
    expect(screen.getByText("доп. работа")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Изменить" }));
    const title = screen.getByRole("textbox", { name: "Название" });
    await user.clear(title);
    await user.type(title, "Ниша 300×200");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(sent.at(-1)?.body).toMatchObject({ title: "Ниша 300×200" });

    await tab(/Позиции/);
    const price = screen.getByRole("textbox", { name: "Цена: Ниша в ГКЛ" });
    await user.clear(price);
    await user.type(price, "abc");
    expect(price).toBeInvalid();
    await user.tab();
    expect(sent).toHaveLength(1);  // a wrong number is not sent
    await user.clear(price);
    await user.type(price, "950,5");
    await user.tab();
    expect(price).toHaveValue("950,50");  // a price is shown back with kopecks
    expect(sent.at(-1)?.body).toEqual({ price: 950.5 });

    await user.click(screen.getByRole("button", { name: "+ Добавить строку" }));
    const lineForm = screen.getByRole("button", { name: "Добавить" }).closest("form")!;
    await user.type(within(lineForm).getByRole("textbox", { name: "Название" }), "Профиль");
    await user.selectOptions(within(lineForm).getByRole("combobox", { name: "Вид" }), "Материалы");
    await user.type(within(lineForm).getByRole("textbox", { name: "Ед." }), "м");
    await user.type(within(lineForm).getByRole("textbox", { name: "Цена" }), "50.5");
    await user.tab();
    expect(within(lineForm).getByRole("textbox", { name: "Цена" })).toHaveValue("50,50");
    await user.click(within(lineForm).getByRole("button", { name: "Добавить" }));
    expect(sent.at(-1)?.body).toEqual({ title: "Профиль", kind: "material", unit: "м", qty: 1, price: 50.5 });

    await user.click(screen.getByRole("checkbox", { name: "Материалы в цене задачи" }));
    expect(sent.at(-1)?.body).toEqual({ materials_included: false });
    await tab(/Настройки/);
    expect(screen.getByRole("button", { name: "Объединить с…" })).toHaveAccessibleDescription("Некуда влить: у остальных задач сумма уже согласована.");
  });

  it("the studio removes a task after a question and closes the card", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ [`DELETE ${W}/tasks/niche`]: workState() });
    const { onClose } = open(task("niche"), STUDIO);
    await tab(/Настройки/);
    ask.mockReturnValueOnce(false);
    await user.click(screen.getByRole("button", { name: "Удалить задачу" }));
    expect(ask).toHaveBeenCalledWith("Удалить задачу «Ниша под роутер в коридоре»?");
    expect(sent).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Удалить задачу" }));
    await vi.waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  });

  it("the studio assigns the task and sets the photo rule", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ [`PATCH ${W}/tasks/water`]: workState() });
    open(task("water"), STUDIO);
    await user.click(screen.getByRole("button", { name: "Исполнитель" }));
    await user.click(screen.getByRole("option", { name: /Петро/ }));
    expect(sent.at(-1)?.body).toEqual({ assignee_id: "u-petro" });
    await tab(/Настройки/);
    await user.selectOptions(screen.getByDisplayValue("обязательно"), "не нужно");
    expect(sent.at(-1)?.body).toEqual({ photo: "none" });
  });

  it("the studio marks a payment (the rest in one click) and deletes one", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ [`POST ${W}/tasks/cable/payments`]: workState(), [`DELETE ${W}/payments/pay2`]: workState() });
    open(task("cable"), STUDIO);
    await tab(/Позиции/);
    const pay = screen.getByRole("button", { name: "Отметить оплату" });
    expect(pay).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /^Остаток:/ }));
    expect(screen.getByRole("textbox", { name: "Сумма" })).toHaveValue("37320,20");
    await user.type(screen.getByRole("textbox", { name: "Примечание" }), "остаток");
    await user.click(pay);
    expect(sent.at(-1)?.body).toMatchObject({ amount: expect.any(Number), note: "остаток" });
    expect((sent.at(-1)?.body as { paid_on: string }).paid_on).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    await user.click(screen.getByRole("button", { name: "Удалить оплату" }));
    expect(sent.at(-1)).toMatchObject({ method: "DELETE", path: `${W}/payments/pay2` });
  });

  it("uploads photos one by one and says per file what was refused", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const sent = stubApi({ [`POST ${W}/tasks/board/photos`]: fail(415, "тип") });
    const { onError } = open(task("board"), INSTALLER);
    expect(screen.getByText("Фото пока нет")).toBeInTheDocument();
    const big = new File(["x"], "big.jpg", { type: "image/jpeg" });
    Object.defineProperty(big, "size", { value: 16 * 1024 * 1024 });
    await user.upload(screen.getByLabelText("Загрузить фото или PDF"), [big, new File(["x"], "a.heic", { type: "image/heic" })]);
    const problems = await screen.findByRole("alert");
    expect(problems).toHaveTextContent("big.jpg: файл больше 15 МБ");
    expect(problems).toHaveTextContent("a.heic: подходят JPEG, PNG, WebP, HEIC или PDF");
    expect(sent).toHaveLength(1);
    expect((sent[0].body as FormData).get("file")).toBeInstanceOf(File);
    expect(onError).toHaveBeenCalled();
  });

  it("the author deletes own photo after a question", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ [`DELETE ${W}/photos/ph2`]: workState() });
    open(task("cable"), INSTALLER);
    expect(screen.getByText("HEIC")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Удалить фото" }));
    expect(ask).toHaveBeenCalledWith("Удалить IMG_0177.HEIC?");
    expect(sent[0].method).toBe("DELETE");
  });

  it("shows the server's refusal with a close; Esc closes the card unless typing", async () => {
    const user = userEvent.setup();
    const { onClose, onError } = open(task("cable"), INSTALLER, { error: "409: задача уже принята" });
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("409: задача уже принята");
    await user.click(within(alert).getByRole("button", { name: "Закрыть" }));
    expect(onError).toHaveBeenCalledOnce();
    await tab(/Лента/);
    await user.click(screen.getByRole("textbox", { name: "Комментарий" }));
    await user.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();
    await user.click(screen.getByRole("heading", { level: 1 }));
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("a materials sum is a plain studio-priced amount, without a provisional mark", async () => {
    open(task("cable"), CLIENT);
    await tab(/Позиции/);
    expect(screen.queryByRole("img", { name: /Цена условная/ })).toBeNull();
    expect(screen.queryByText(/имитаци/)).toBeNull();
  });

  it("before approval the client only reads: ticks come later, no status buttons", () => {
    open(draftState("proposed", CLIENT).tasks[1], CLIENT, { state: draftState("proposed", CLIENT) });
    expect(screen.getByText("Отмечать пункты можно после утверждения плана.")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "кабель лежит по трассе и закреплён" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Принять" })).toBeNull();
  });

  it("tabs: the top stays, one tab is rendered at a time; the client has no settings", async () => {
    open(task("cable"), CLIENT, { me: null });
    expect(screen.getByRole("tablist", { name: "Разделы карточки" })).toBeInTheDocument();
    const names = screen.getAllByRole("tab").map((x) => x.textContent);
    expect(names[0]).toBe("Работа");
    expect(names[1]).toMatch(/^Позиции47\s320,20\sгрн$/);   // the task sum
    expect(names[2]).toBe("Лента3");                        // the number of entries
    expect(names).toHaveLength(3);
    expect(screen.queryByRole("tab", { name: "Настройки" })).toBeNull();
    // "Work" is open: the criterion and the photos; the lines and the feed are not in the DOM
    expect(screen.getByRole("tab", { name: "Работа" })).toHaveAttribute("aria-selected", "true");   // the photo is there: no mark
    expect(screen.getByRole("checkbox", { name: "концы промаркированы" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Комментарий" })).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByDisplayValue("обязательно")).toBeNull();   // the photo rule is a setting of the studio
    await tab(/Лента/);
    expect(screen.getByText("Закреплю завтра утром, пришлю фото.")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "концы промаркированы" })).toBeNull();
    // the top is still there
    expect(screen.getByRole("heading", { level: 1, name: "Прокладка кабеля" })).toBeInTheDocument();
    expect(screen.getByText("Исполнитель").parentElement).toHaveTextContent("ИсполнительПетро");
  });

  it("the studio has the settings tab: photo rule, order, merge, delete", async () => {
    open(task("niche"), STUDIO);
    await tab(/Настройки/);
    expect(screen.getByDisplayValue("по желанию")).toBeInTheDocument();
    expect(screen.getByText("Порядок")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Объединить с…" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Удалить задачу" })).toBeInTheDocument();
  });

  it("accepting waits for every point of the criterion to be ticked", () => {
    open({ ...task("cable"), status: "review" }, CLIENT, { me: null });
    const accept = screen.getByRole("button", { name: "Принять" });
    expect(accept).toBeDisabled();
    expect(accept).toHaveAccessibleDescription("Сначала отметьте все пункты критерия приёмки: не отмечено 1 из 3.");
    expect(screen.getByRole("button", { name: "Вернуть" })).toBeEnabled();
    expect(screen.getByRole("tab", { name: "Работа — требует внимания" })).toBeInTheDocument();
  });

  it("an intent from the board opens the return form, or the confirm dialog for the studio", async () => {
    const sent = stubApi({ [`POST ${W}/tasks/boxes/status`]: workState() });
    const { onIntent, unmount } = open(task("boxes"), CLIENT, { me: null, intent: "returned", onIntent: vi.fn() });
    expect(screen.getByRole("textbox", { name: "Что исправить" })).toBeInTheDocument();
    expect(onIntent).toHaveBeenCalledOnce();
    expect(sent).toHaveLength(0);
    unmount();
    open(task("boxes"), STUDIO, { intent: "accepted" });
    expect(screen.getByRole("dialog", { name: "Как заказчик подтвердил?" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "По звонку" }));
    await userEvent.click(screen.getByRole("button", { name: "Подтвердить за заказчика" }));
    expect(sent[0].body).toEqual({ to: "accepted", on_behalf: "phone" });
  });

  it("an intent for a blocked transition presses nothing: the hint says why", () => {
    const sent = stubApi({});
    open({ ...task("cable"), status: "review" }, CLIENT, { me: null, intent: "accepted" });
    expect(sent).toHaveLength(0);
    expect(screen.queryByRole("textbox", { name: "Что исправить" })).toBeNull();
    expect(screen.getByText(/Сначала отметьте все пункты/)).toBeInTheDocument();
  });
});
