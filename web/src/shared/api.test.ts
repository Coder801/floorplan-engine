import { afterEach, describe, expect, it, vi } from "vitest";
import { AnswerRefused, base, isProject, saveAnswer } from "./api";

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
