import { afterEach, describe, expect, it, vi } from "vitest";
import {
  AnswerRefused, base, behalfBody, FeedbackError, sendFeedback, deleteWorkPayment, editWorkLine, editWorkTask, getWork, isProject, mergeWorkTask, moveWorkLines,
  saveAnswer, setWorkCheck, setWorkStatus, uploadWorkPhoto, WorkError, workPlanAction,
} from "./api";

describe("project key", () => {
  const p = { id: "6f1c0b2e-0000-4000-8000-000000000001", name: "kv42" };
  it("opens by the id and by an old link by name", () => {
    expect(isProject(p, p.id)).toBe(true);
    expect(isProject(p, "kv42")).toBe(true);
    expect(isProject(p, "kv43")).toBe(false);
    expect(isProject(p, null)).toBe(false);
  });
  it("puts the key into the API address", () => {
    expect(base("кв 1")).toBe("/api/projects/%D0%BA%D0%B2%201");
  });
});

describe("ответ на вопрос", () => {
  const reply = (status: number, body: unknown) => vi.stubGlobal("fetch", async () => new Response(JSON.stringify(body), { status }));
  afterEach(() => vi.unstubAllGlobals());

  it("отказ проверки — ошибки по полям и мешающие ответы", async () => {
    const detail = { issues: [{ file: "room.yaml", path: "rooms[0].walls", message: "контур" }], blocked_by: [{ id: "q1", text: "?" }] };
    reply(422, { detail });
    const refused = await saveAnswer("kv", "q2", 5).catch((e: unknown) => e);
    expect(refused).toBeInstanceOf(AnswerRefused);
    expect((refused as AnswerRefused).issues[0].path).toBe("rooms[0].walls");
    expect((refused as AnswerRefused).blockedBy[0].id).toBe("q1");
  });
  it("другая ошибка — обычная, ответ — как есть", async () => {
    reply(422, { detail: "id: нужен id вопроса" });
    await expect(saveAnswer("kv", "", 5)).rejects.toThrow("422: id: нужен");
    reply(200, { built: false, rebuilt: false });
    await expect(saveAnswer("kv", "q1", { text: "т" })).resolves.toEqual({ built: false, rebuilt: false });
  });
});

describe("монтаж по задачам", () => {
  const STATE = { plan: null, tasks: [], draft_available: true, model_version: 1, assignees: [], can: { work_do: true, work_accept: true, work_manage: true } };
  const calls: { url: string; init?: RequestInit }[] = [];
  const reply = (status: number, body: unknown) => {
    calls.length = 0;
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return new Response(JSON.stringify(body), { status });
    });
  };
  const last = () => calls[calls.length - 1];
  afterEach(() => vi.unstubAllGlobals());

  it("запись отвечает всем состоянием; адрес и тело — по контракту", async () => {
    reply(200, STATE);
    await expect(setWorkStatus("kv 1", "t/1", "returned", "переделать")).resolves.toEqual(STATE);
    expect(last().url).toBe("/api/projects/kv%201/work/tasks/t%2F1/status");
    expect(last().init?.method).toBe("POST");
    expect(JSON.parse(last().init?.body as string)).toEqual({ to: "returned", comment: "переделать" });

    await setWorkStatus("kv", "t1", "in_progress");
    expect(JSON.parse(last().init?.body as string)).toEqual({ to: "in_progress" });
    await workPlanAction("kv", "approve");
    expect(last().url).toBe("/api/projects/kv/work/plan/approve");
    await editWorkLine("kv", "t1", "l1", { fact_qty: null });
    expect(last().init?.method).toBe("PATCH");
    expect(JSON.parse(last().init?.body as string)).toEqual({ fact_qty: null });
    await deleteWorkPayment("kv", "p1");
    expect([last().url, last().init?.method]).toEqual(["/api/projects/kv/work/payments/p1", "DELETE"]);
    await getWork("kv");
    expect(last().url).toBe("/api/projects/kv/work");
  });

  it("за заказчика: канал и примечание в теле; заказчик и пустое примечание — без полей", async () => {
    reply(200, STATE);
    await workPlanAction("kv", "approve", { channel: "phone", note: " звонок 12.11 " });
    expect(JSON.parse(last().init?.body as string)).toEqual({ on_behalf: "phone", note: "звонок 12.11" });
    await workPlanAction("kv", "approve");
    expect(last().init?.body).toBeUndefined();
    await setWorkStatus("kv", "t1", "returned", "переделать", { channel: "telegram", note: "" });
    expect(JSON.parse(last().init?.body as string)).toEqual({ to: "returned", comment: "переделать", on_behalf: "telegram" });
    await setWorkStatus("kv", "t1", "accepted", undefined, { channel: "other", note: "на объекте" });
    expect(JSON.parse(last().init?.body as string)).toEqual({ to: "accepted", on_behalf: "other", note: "на объекте" });
    expect(behalfBody(null)).toEqual({});
  });

  it("галочка, объединение, перенос строк, порядок и after — адрес, метод и тело по контракту", async () => {
    reply(200, STATE);
    await setWorkCheck("kv", "t1", 2, true);
    expect([last().url, last().init?.method]).toEqual(["/api/projects/kv/work/tasks/t1/checks", "PATCH"]);
    expect(JSON.parse(last().init?.body as string)).toEqual({ index: 2, checked: true });
    await mergeWorkTask("kv", "t1", "t2");
    expect([last().url, last().init?.method]).toEqual(["/api/projects/kv/work/tasks/t1/merge", "POST"]);
    expect(JSON.parse(last().init?.body as string)).toEqual({ into: "t2" });
    await moveWorkLines("kv", "t1", ["l1", "l2"], "t3");
    expect([last().url, last().init?.method]).toEqual(["/api/projects/kv/work/tasks/t1/lines/move", "POST"]);
    expect(JSON.parse(last().init?.body as string)).toEqual({ line_ids: ["l1", "l2"], to_task: "t3" });
    await editWorkTask("kv", "t1", { position: 0 });
    expect(JSON.parse(last().init?.body as string)).toEqual({ position: 0 });
    await editWorkTask("kv", "t1", { after: ["t2"] });
    expect([last().url, last().init?.method]).toEqual(["/api/projects/kv/work/tasks/t1", "PATCH"]);
    expect(JSON.parse(last().init?.body as string)).toEqual({ after: ["t2"] });
  });

  it("круг в after и закрытые деньги — WorkError с текстом сервера", async () => {
    reply(422, { detail: "after: зависимость по кругу: «А» → «Б» → «А»" });
    const e = await editWorkTask("kv", "t1", { after: ["t2"] }).catch((x: unknown) => x);
    expect((e as WorkError).status).toBe(422);
    expect((e as WorkError).message).toBe("after: зависимость по кругу: «А» → «Б» → «А»");
    reply(409, { detail: "сумма задачи согласована с заказчиком" });
    await expect(mergeWorkTask("kv", "t1", "t2")).rejects.toMatchObject({ status: 409 });
  });

  it("фото — multipart с полем file, без своего Content-Type", async () => {
    reply(200, STATE);
    await uploadWorkPhoto("kv", "t1", new File(["x"], "IMG_1.HEIC", { type: "image/heic" }), "штроба");
    const body = last().init?.body as FormData;
    expect(body).toBeInstanceOf(FormData);
    expect((body.get("file") as File).name).toBe("IMG_1.HEIC");
    expect(body.get("caption")).toBe("штроба");
    expect(last().init?.headers).toBeUndefined();
  });

  it("отказ — WorkError со статусом и текстом сервера", async () => {
    reply(413, { detail: "файл больше 15 МБ" });
    const e = await uploadWorkPhoto("kv", "t1", new File(["x"], "a.jpg")).catch((x: unknown) => x);
    expect(e).toBeInstanceOf(WorkError);
    expect((e as WorkError).status).toBe(413);
    expect((e as WorkError).message).toBe("файл больше 15 МБ");
  });
});

describe("отзыв о сервисе", () => {
  const CONTEXT = { sheet: "plan", path: "/#kv", version: "0.5.1 (b)", viewport: "1440×900", user_agent: "UA" };
  const calls: { url: string; init?: RequestInit }[] = [];
  const reply = (status: number, body: unknown) => {
    calls.length = 0;
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return new Response(JSON.stringify(body), { status, statusText: status === 422 ? "Unprocessable" : "" });
    });
  };
  afterEach(() => vi.unstubAllGlobals());

  it("multipart: вид, текст, контекст строкой JSON, проект и скриншоты", async () => {
    reply(200, { id: "f1" });
    const shot = new File(["x"], "a.png", { type: "image/png" });
    await expect(sendFeedback({ kind: "bug", text: "не жмётся", context: CONTEXT, project: "kv", photos: [shot, shot] }))
      .resolves.toEqual({ id: "f1" });
    expect(calls[0].url).toBe("/api/feedback");
    expect(calls[0].init?.method).toBe("POST");
    const form = calls[0].init?.body as FormData;
    expect(form.get("kind")).toBe("bug");
    expect(form.get("text")).toBe("не жмётся");
    expect(JSON.parse(form.get("context") as string)).toEqual(CONTEXT);
    expect(form.get("project")).toBe("kv");
    expect(form.getAll("photos")).toHaveLength(2);
  });
  it("без проекта и скриншотов — без этих полей", async () => {
    reply(200, { id: "f2" });
    await sendFeedback({ kind: "idea", text: "т", context: CONTEXT, project: null });
    const form = calls[0].init?.body as FormData;
    expect(form.has("project")).toBe(false);
    expect(form.has("photos")).toBe(false);
  });
  it("отказ — статус и текст сервера; список ошибок — словами статуса", async () => {
    reply(429, { detail: "Слишком часто" });
    const e = await sendFeedback({ kind: "other", text: "т", context: CONTEXT }).catch((x: unknown) => x);
    expect(e).toBeInstanceOf(FeedbackError);
    expect(e).toMatchObject({ status: 429, message: "Слишком часто" });
    reply(422, { detail: [{ loc: ["body", "text"] }] });
    await expect(sendFeedback({ kind: "other", text: "т", context: CONTEXT })).rejects.toMatchObject({ status: 422, message: "Unprocessable" });
  });
});
