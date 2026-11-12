import { describe, expect, it } from "vitest";
import i18n from "./i18n";
import type { WorkCan, WorkPhoto, WorkPlan, WorkPlanState, WorkState, WorkStatus, WorkTask, WorkTotals } from "./types";
import {
  actsForClient, afterOf, allDone, behalfText, boardColumns, byColumn, byDomain, canDeletePhoto, canMoveLines, cardRights,
  day, emptyOf, feedOf, layoutOf, mergeBlock, mergeTargets, modelChanged, money, needsBehalf, numberOf, parseAmount,
  planActions, planNeed, progressOf, shiftTo, statusButtons, taskNeed, ticked, today,
} from "./work";

const CAN = {
  studio: { work_do: true, work_accept: true, work_manage: true },
  installer: { work_do: true, work_accept: false, work_manage: false },
  client: { work_do: false, work_accept: true, work_manage: false },
  viewer: { work_do: false, work_accept: false, work_manage: false },
} satisfies Record<string, WorkCan>;

const totals = (over: Partial<WorkTotals> = {}): WorkTotals =>
  ({ work: 100, material: 50, total: 150, paid: 0, tasks: 2, accepted: 0, settled: 0, unpriced: 0, ...over });
const plan = (state: WorkPlanState, over: Partial<WorkPlan> = {}): WorkPlan => ({
  id: "p", state, currency: "грн", model_version: 3, created_at: null, approved_at: null, approved_by: null,
  approved_on_behalf: null, closed_at: null, totals: totals(), ...over,
});
const photo = (over: Partial<WorkPhoto> = {}): WorkPhoto => ({
  id: "ph", url: "/x", file_name: "a.jpg", content_type: "image/jpeg", size: 1, caption: "", author: "Петро",
  user_id: "u1", created_at: null, ...over,
});
const task = (over: Partial<WorkTask> = {}): WorkTask => ({
  id: "t1", key: "electrical.cable", domain: "electrical", position: 0, title: "Прокладка кабеля", description: "",
  status: "todo", extra: false, photo: "optional", result: [], checked: [], after: [], waiting: [], assignee: null,
  materials_included: true, money_editable: false, lines: [], work_total: 100, material_total: 50, total: 150,
  paid: 0, settled: false, unpriced: 0, photos: [], comments: [], payments: [], ...over,
});
const state = (over: Partial<WorkState> = {}): WorkState => ({
  plan: plan("approved"), tasks: [task()], draft_available: true, model_version: 3, assignees: [], can: CAN.studio, ...over,
});

describe("кто что видит", () => {
  it("доска — студии и монтажнику, список — заказчику и коду просмотра", () => {
    expect(layoutOf(CAN.studio)).toBe("board");
    expect(layoutOf(CAN.installer)).toBe("board");
    expect(layoutOf(CAN.client)).toBe("list");
    expect(layoutOf(CAN.viewer)).toBe("list");
  });

  it("пусто: студии — создать из сметы или пересобрать, остальным — студия готовит план", () => {
    expect(emptyOf(state({ plan: null, tasks: [] }))).toBe("create");
    expect(emptyOf(state({ plan: null, tasks: [], draft_available: false }))).toBe("noDraft");
    expect(emptyOf(state({ plan: null, tasks: [], can: CAN.client }))).toBe("preparing");
    expect(emptyOf(state({ plan: null, tasks: [], can: CAN.installer }))).toBe("preparing");
    // Черновик, который студия не отправила, заказчик не видит
    expect(emptyOf(state({ plan: plan("draft"), can: CAN.client }))).toBe("preparing");
    expect(emptyOf(state({ plan: plan("draft") }))).toBeNull();
    expect(emptyOf(state({ plan: plan("proposed"), can: CAN.client }))).toBeNull();
  });
});

describe("доска", () => {
  const tasks = [
    task({ id: "a", status: "accepted", position: 2 }),
    task({ id: "b", status: "todo", position: 1, domain: "plumbing" }),
    task({ id: "c", status: "todo", position: 0, domain: "other" }),
  ];
  it("план до утверждения — одна колонка предложенных", () => {
    expect(boardColumns(plan("draft"), tasks)).toEqual(["proposed"]);
    expect(boardColumns(plan("proposed"), tasks)).toEqual(["proposed"]);
    expect(boardColumns(null, tasks)).toEqual([]);
  });
  it("утверждённый — колонки работ, «Предложено» — только пока есть доп. работа", () => {
    expect(boardColumns(plan("approved"), tasks)).toEqual(["todo", "in_progress", "review", "returned", "accepted"]);
    expect(boardColumns(plan("approved"), [...tasks, task({ status: "proposed", extra: true })])[0]).toBe("proposed");
  });
  it("задачи по колонкам в порядке работ", () => {
    const cols = byColumn(tasks);
    expect(cols.todo.map((t) => t.id)).toEqual(["c", "b"]);
    expect(cols.accepted.map((t) => t.id)).toEqual(["a"]);
    expect(cols.review).toEqual([]);
  });
  it("переключатель разделов: «всё» — со своими задачами студии", () => {
    expect(byDomain(tasks, "all")).toHaveLength(3);
    expect(byDomain(tasks, "plumbing").map((t) => t.id)).toEqual(["b"]);
    expect(byDomain(tasks, "electrical").map((t) => t.id)).toEqual(["a"]);
  });
  it("прогресс: принято N из M, оплачено X из Y", () => {
    expect(progressOf(totals({ accepted: 1, tasks: 4, paid: 75, total: 150 }))).toEqual(
      { accepted: 1, tasks: 4, paid: 75, total: 150, done: 0.25, money: 0.5 });
    expect(progressOf(totals({ tasks: 0, total: 0, accepted: 0 })).done).toBe(0);
    expect(progressOf(totals({ paid: 300, total: 150 })).money).toBe(1);
  });
});

describe("кнопки плана", () => {
  it("по состоянию плана и правам", () => {
    expect(planActions(state({ plan: null }))).toEqual(["create"]);
    expect(planActions(state({ plan: null, draft_available: false }))).toEqual([]);
    expect(planActions(state({ plan: null, can: CAN.installer }))).toEqual([]);
    expect(planActions(state({ plan: plan("draft") }))).toEqual(["propose", "discard"]);
    expect(planActions(state({ plan: plan("proposed"), can: CAN.client }))).toEqual(["approve"]);
    expect(planActions(state({ plan: plan("proposed"), can: CAN.installer }))).toEqual([]);
    expect(planActions(state({ plan: plan("approved") }))).toEqual(["add"]);
    expect(planActions(state({ plan: plan("approved"), can: CAN.client }))).toEqual([]);
    expect(planActions(state({ plan: plan("closed") }))).toEqual([]);
  });
  it("закрыть — когда всё принято и оплачено", () => {
    const done = plan("approved", { totals: totals({ tasks: 2, accepted: 2, settled: 2 }) });
    expect(planActions(state({ plan: done }))).toEqual(["add", "close"]);
    expect(allDone(totals({ tasks: 2, accepted: 2, settled: 1 }))).toBe(false);
    expect(allDone(totals({ tasks: 0, accepted: 0, settled: 0 }))).toBe(false);
  });
  it("заказчику — «Утвердите план», пока план у него", () => {
    expect(planNeed(state({ plan: plan("proposed"), can: CAN.client }))).toBe("approvePlan");
    expect(planNeed(state({ plan: plan("proposed"), can: CAN.installer }))).toBeNull();
    expect(planNeed(state({ plan: plan("approved"), can: CAN.client }))).toBeNull();
  });
});

describe("кнопки статуса — по таблице переходов", () => {
  const actions = (status: WorkStatus, can: WorkCan, over: Partial<WorkTask> = {}) =>
    statusButtons(task({ status, ...over }), plan("approved"), can).map((b) => b.action);

  it("монтажник берёт, сдаёт, берёт снова; принять и вернуть не может", () => {
    expect(actions("todo", CAN.installer)).toEqual(["take"]);
    expect(actions("in_progress", CAN.installer)).toEqual(["handIn"]);
    expect(actions("returned", CAN.installer)).toEqual(["handIn", "retake"]);
    expect(actions("review", CAN.installer)).toEqual([]);
    expect(actions("accepted", CAN.installer)).toEqual([]);
    expect(actions("proposed", CAN.installer, { extra: true })).toEqual([]);
  });
  it("заказчик принимает, возвращает, согласует доп. работу; работать не может", () => {
    expect(actions("review", CAN.client)).toEqual(["accept", "return"]);
    expect(actions("proposed", CAN.client, { extra: true })).toEqual(["agree"]);
    expect(actions("todo", CAN.client)).toEqual([]);
    expect(actions("in_progress", CAN.client)).toEqual([]);
  });
  it("код просмотра только смотрит; до утверждения плана статусы не меняются", () => {
    expect(actions("review", CAN.viewer)).toEqual([]);
    expect(statusButtons(task({ status: "proposed" }), plan("proposed"), CAN.studio)).toEqual([]);
    expect(statusButtons(task({ status: "todo" }), plan("closed"), CAN.studio)).toEqual([]);
  });
  it("вернуть — с комментарием, первая кнопка — главная", () => {
    const [accept, ret] = statusButtons(task({ status: "review" }), plan("approved"), CAN.client);
    expect(accept).toMatchObject({ to: "accepted", primary: true, comment: false });
    expect(ret).toMatchObject({ to: "returned", primary: false, comment: true });
  });
  it("обязательное фото: «Сдать» заблокирована, пока фото нет", () => {
    const need = statusButtons(task({ status: "in_progress", photo: "required" }), plan("approved"), CAN.installer)[0];
    expect(need.blocked).toBe("photo");
    const has = statusButtons(task({ status: "in_progress", photo: "required", photos: [photo()] }), plan("approved"), CAN.installer)[0];
    expect(has.blocked).toBeNull();
    const back = statusButtons(task({ status: "returned", photo: "required" }), plan("approved"), CAN.installer);
    expect(back.map((b) => b.blocked)).toEqual(["photo", null]);
  });
  it("задача ждёт другие: монтажнику взять нельзя, студии можно", () => {
    const waiting = { waiting: [{ id: "x", title: "Штробы" }] };
    expect(statusButtons(task(waiting), plan("approved"), CAN.installer)[0].blocked).toBe("waiting");
    expect(statusButtons(task(waiting), plan("approved"), CAN.studio)[0].blocked).toBeNull();
  });
  it("что нужно от заказчика по задаче", () => {
    expect(taskNeed(task({ status: "review" }), plan("approved"), CAN.client)).toBe("acceptWork");
    expect(taskNeed(task({ status: "proposed", extra: true }), plan("approved"), CAN.client)).toBe("agreeExtra");
    expect(taskNeed(task({ status: "proposed" }), plan("proposed"), CAN.client)).toBeNull();
    expect(taskNeed(task({ status: "review" }), plan("approved"), CAN.installer)).toBeNull();
  });
});

describe("права карточки", () => {
  it("факт — монтажнику, пока задача в работе", () => {
    expect(cardRights(task({ status: "in_progress" }), plan("approved"), CAN.installer).fact).toBe(true);
    expect(cardRights(task({ status: "accepted" }), plan("approved"), CAN.installer).fact).toBe(false);
    expect(cardRights(task({ status: "proposed" }), plan("approved"), CAN.installer).fact).toBe(false);
    expect(cardRights(task({ status: "todo" }), plan("draft"), CAN.installer).fact).toBe(false);
    expect(cardRights(task({ status: "todo" }), plan("approved"), CAN.client).fact).toBe(false);
  });
  it("деньги — студии, пока сумма не согласована", () => {
    expect(cardRights(task({ money_editable: true }), plan("draft"), CAN.studio).money).toBe(true);
    expect(cardRights(task({ money_editable: false }), plan("approved"), CAN.studio).money).toBe(false);
    expect(cardRights(task({ money_editable: true }), plan("draft"), CAN.installer).money).toBe(false);
  });
  it("фото и оплаты — после утверждения; в закрытом плане ничего", () => {
    expect(cardRights(task(), plan("draft"), CAN.studio)).toMatchObject({ photos: false, payments: false, comment: true });
    expect(cardRights(task(), plan("approved"), CAN.client)).toMatchObject({ photos: true, payments: false, comment: true });
    expect(cardRights(task(), plan("approved"), CAN.viewer)).toMatchObject({ photos: false, comment: false });
    const closed = cardRights(task(), plan("closed"), CAN.studio);
    expect(Object.values(closed).every((v) => v === false)).toBe(true);
  });
  it("удалить задачу — не начатую, без фото и оплат", () => {
    expect(cardRights(task({ status: "todo" }), plan("approved"), CAN.studio).remove).toBe(true);
    expect(cardRights(task({ status: "in_progress" }), plan("approved"), CAN.studio).remove).toBe(false);
    expect(cardRights(task({ status: "todo", photos: [photo()] }), plan("approved"), CAN.studio).remove).toBe(false);
    expect(cardRights(task({ status: "todo" }), plan("approved"), CAN.installer).remove).toBe(false);
  });
  it("фото удаляет автор до приёмки или студия; фото с кода — только студия", () => {
    const own = photo({ user_id: "me" });
    expect(canDeletePhoto(own, task({ status: "review" }), plan("approved"), CAN.installer, "me")).toBe(true);
    expect(canDeletePhoto(own, task({ status: "accepted" }), plan("approved"), CAN.installer, "me")).toBe(false);
    expect(canDeletePhoto(own, task(), plan("approved"), CAN.installer, "other")).toBe(false);
    expect(canDeletePhoto(photo({ user_id: null }), task(), plan("approved"), CAN.client, null)).toBe(false);
    expect(canDeletePhoto(photo({ user_id: null }), task({ status: "accepted" }), plan("approved"), CAN.studio, null)).toBe(true);
    expect(canDeletePhoto(own, task(), plan("closed"), CAN.studio, "me")).toBe(false);
  });
});

describe("форматы", () => {
  it("деньги: слово валюты из сметы или код ISO, копейки — только если есть", () => {
    expect(money(20719.6, "грн", "ru-RU")).toBe("20 719,60 грн");
    expect(money(1500, "грн", "ru-RU")).toBe("1 500 грн");
    expect(money(1500, "", "en-GB")).toBe("1,500");
    expect(money(1500, "EUR", "en-GB")).toBe("€1,500");
  });
  it("день оплаты — календарный, без сдвига по поясу", () => {
    expect(day("2026-11-01", "en-GB")).toBe("1 Nov 2026");
    expect(day("не дата", "en-GB")).toBe("не дата");
    expect(today(new Date(2026, 0, 5))).toBe("2026-01-05");
  });
  it("число из поля: запятая, пробелы, пусто — null, неверное — undefined", () => {
    expect(parseAmount("1 234,5")).toBe(1234.5);
    expect(parseAmount("")).toBeNull();
    expect(parseAmount("abc")).toBeUndefined();
    expect(parseAmount("-3")).toBeUndefined();
  });
  it("лента — от старых к новым; модель менялась после плана", () => {
    const c = (id: string, created_at: string) => ({ id, kind: "comment" as const, status: null, text: "", author: "", user_id: null, on_behalf: null, created_at });
    expect(feedOf([c("b", "2026-11-12T10:00:00"), c("a", "2026-11-11T10:00:00")]).map((x) => x.id)).toEqual(["a", "b"]);
    expect(modelChanged(state({ model_version: 4 }))).toBe(true);
    expect(modelChanged(state())).toBe(false);
    expect(modelChanged(state({ plan: null }))).toBe(false);
  });
});

describe("студия за заказчика (решение 2026-11-12)", () => {
  it("канал спрашивают у студии, у заказчика и кода — никогда", () => {
    expect(actsForClient(CAN.studio)).toBe(true);
    expect(actsForClient(CAN.client)).toBe(false);
    expect(actsForClient(CAN.installer)).toBe(false);   // нет work_accept: действия заказчика ему не даны
    expect(actsForClient(CAN.viewer)).toBe(false);
  });
  it("нужен канал: утвердить план, согласовать, принять, вернуть; взять и сдать — нет", () => {
    for (const a of ["approve", "agree", "accept", "return"] as const) {
      expect(needsBehalf(a, CAN.studio)).toBe(true);
      expect(needsBehalf(a, CAN.client)).toBe(false);
    }
    for (const a of ["take", "handIn", "retake", "propose", "close", "discard", "create", "add"] as const) {
      expect(needsBehalf(a, CAN.studio)).toBe(false);
    }
  });
  it("кнопки статуса помечены: студии — с каналом, заказчику — без", () => {
    const review = task({ status: "review" });
    expect(statusButtons(review, plan("approved"), CAN.studio).map((b) => [b.action, b.behalf]))
      .toEqual([["accept", true], ["return", true]]);
    expect(statusButtons(review, plan("approved"), CAN.client).every((b) => !b.behalf)).toBe(true);
    expect(statusButtons(task({ status: "todo" }), plan("approved"), CAN.studio)[0]).toMatchObject({ action: "take", behalf: false });
    expect(statusButtons(task({ status: "proposed", extra: true }), plan("approved"), CAN.studio)[0])
      .toMatchObject({ action: "agree", behalf: true });
  });
  it("канал словами: в ленте и в плане, примечание — после двоеточия", async () => {
    await i18n.changeLanguage("ru");
    expect(behalfText({ channel: "phone", note: " звонок 12.11 " }, "feed")).toBe("студия за заказчика — по звонку: звонок 12.11");
    expect(behalfText({ channel: "telegram", note: "" }, "plan")).toBe("Утверждён студией за заказчика — в Telegram");
  });
});

describe("галочки критерия приёмки", () => {
  it("отмечают монтажник и заказчик в утверждённом и не закрытом плане", () => {
    const t1 = task({ result: ["a", "b"] });
    expect(cardRights(t1, plan("approved"), CAN.installer).tick).toBe(true);
    expect(cardRights(t1, plan("approved"), CAN.client).tick).toBe(true);
    expect(cardRights(t1, plan("approved"), CAN.viewer).tick).toBe(false);
    expect(cardRights(t1, plan("proposed"), CAN.client).tick).toBe(false);
    expect(cardRights(t1, plan("draft"), CAN.studio).tick).toBe(false);
    expect(cardRights(t1, plan("closed"), CAN.studio).tick).toBe(false);
  });
  it("отметка — по возрастанию, без повторов", () => {
    expect(ticked([2], 0, true)).toEqual([0, 2]);
    expect(ticked([0, 2], 0, true)).toEqual([0, 2]);
    expect(ticked([0, 2], 2, false)).toEqual([0]);
    expect(ticked([], 1, false)).toEqual([]);
  });
});

describe("объединение и перенос строк", () => {
  const open = (id: string, position: number, over: Partial<WorkTask> = {}) => task({ id, position, money_editable: true, ...over });
  const tasks = [open("b", 1), open("a", 0), task({ id: "c", position: 2, money_editable: false }), open("d", 3)];
  it("куда влить: другие задачи с открытыми деньгами, по порядку", () => {
    expect(mergeTargets(tasks[1], state({ plan: plan("draft"), tasks })).map((t) => t.id)).toEqual(["b", "d"]);
  });
  it("никуда: деньги задачи согласованы, план закрыт или нет права", () => {
    expect(mergeTargets(tasks[2], state({ tasks }))).toEqual([]);
    expect(mergeTargets(tasks[1], state({ plan: plan("closed"), tasks }))).toEqual([]);
    expect(mergeTargets(tasks[1], state({ plan: plan("draft"), tasks, can: CAN.installer }))).toEqual([]);
    expect(mergeTargets(tasks[1], state({ plan: null, tasks }))).toEqual([]);
  });
  it("кнопка выключена с причиной: фото, оплаты, некуда", () => {
    const targets = [tasks[0]];
    expect(mergeBlock(open("x", 0, { photos: [photo()] }), targets)).toBe("photos");
    expect(mergeBlock(open("x", 0, { payments: [{ id: "p", amount: 1, paid_on: "2026-11-12", note: "", created_at: null }] }), targets)).toBe("payments");
    expect(mergeBlock(open("x", 0), [])).toBe("noTargets");
    expect(mergeBlock(open("x", 0), targets)).toBeNull();
  });
  it("строки переносятся, если есть куда и что", () => {
    const line = { id: "l", key: "k", kind: "work" as const, title: "x", unit: "м", plan_qty: 1, fact_qty: null, price: 1, sum: 1 };
    expect(canMoveLines(open("x", 0, { lines: [line] }), [tasks[0]])).toBe(true);
    expect(canMoveLines(open("x", 0), [tasks[0]])).toBe(false);
    expect(canMoveLines(open("x", 0, { lines: [line] }), [])).toBe(false);
  });
});

describe("порядок и «после каких задач»", () => {
  const tasks = [
    task({ id: "a", key: "electrical.chases", position: 0 }),
    task({ id: "b", key: null, position: 1 }),
    task({ id: "c", key: "electrical.cable", position: 2, after: ["electrical.chases", "b", "c", "нет"] }),
  ];
  it("выше и ниже — место соседа; у краёв — некуда", () => {
    expect(shiftTo(tasks, "b", -1)).toBe(0);
    expect(shiftTo(tasks, "b", 1)).toBe(2);
    expect(shiftTo(tasks, "a", -1)).toBeNull();
    expect(shiftTo(tasks, "c", 1)).toBeNull();
    expect(shiftTo(tasks, "нет", 1)).toBeNull();
  });
  it("сосед — в показанном списке: скрытый раздел не мешает", () => {
    const shown = [tasks[0], tasks[2]];
    expect(shiftTo(shown, "c", -1)).toBe(0);
  });
  it("after — по id или ключу; сама задача и неизвестные отбрасываются", () => {
    expect(afterOf(tasks[2], tasks).map((t) => t.id)).toEqual(["a", "b"]);
    expect(afterOf(tasks[0], tasks)).toEqual([]);
  });
  it("номер в плане — с единицы по порядку работ", () => {
    expect(numberOf(tasks[2], [tasks[2], tasks[0], tasks[1]])).toBe(3);
  });
  it("порядок и after правит только студия в незакрытом плане", () => {
    expect(cardRights(tasks[0], plan("approved"), CAN.studio).manage).toBe(true);
    expect(cardRights(tasks[0], plan("approved"), CAN.installer).manage).toBe(false);
    expect(cardRights(tasks[0], plan("closed"), CAN.studio).manage).toBe(false);
  });
});
