import { afterEach, describe, expect, it, vi } from "vitest";
import { fail, stubApi } from "./testApi";
import { ThreadError, threadsApi } from "./threads";

const T = "/api/projects/kv%2042/threads";
const row = { id: "t 1", state: "open", question: null, chain: 1, messages: [], waiting_for: "studio", waiting_for_you: true };

describe("API тредов", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("список — { threads, waiting_for_you }, тред — с цепочкой previous", async () => {
    stubApi({ [`GET ${T}`]: { threads: [row], waiting_for_you: 1 }, [`GET ${T}/t%201`]: { ...row, previous: [] } });
    expect(await threadsApi.list("kv 42")).toEqual({ threads: [row], waiting_for_you: 1 });
    expect(await threadsApi.get("kv 42", "t 1")).toMatchObject({ id: "t 1", previous: [] });
  });

  it("сообщение, принятие и закрытие — POST с телом, ответ — тред", async () => {
    const sent = stubApi({
      [`POST ${T}/t%201/messages`]: { ...row, messages_count: 1 },
      [`POST ${T}/t%201/accept`]: { ...row, state: "checking" },
      [`POST ${T}/t%201/close`]: { ...row, state: "closed" },
    });
    expect(await threadsApi.send("kv 42", "t 1", "у окна")).toMatchObject({ messages_count: 1 });
    expect(await threadsApi.accept("kv 42", "t 1", "m1")).toMatchObject({ state: "checking" });
    await threadsApi.close("kv 42", "t 1");
    expect(await threadsApi.close("kv 42", "t 1", "решено правкой")).toMatchObject({ state: "closed" });
    expect(sent.map((s) => [s.method, s.path.slice(T.length), s.body])).toEqual([
      ["POST", "/t%201/messages", { text: "у окна" }],
      ["POST", "/t%201/accept", { message_id: "m1" }],
      ["POST", "/t%201/close", {}],
      ["POST", "/t%201/close", { comment: "решено правкой" }],
    ]);
  });

  it("202 с тредом — принято", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ ...row, state: "checking" }), { status: 202 }));
    await expect(threadsApi.accept("kv 42", "t1", "m1")).resolves.toMatchObject({ state: "checking" });
  });

  it("отказ — ThreadError со статусом и текстом сервера", async () => {
    stubApi({ [`POST ${T}/t1/accept`]: fail(409, "Тред уже проверяется"), [`GET ${T}`]: fail(404, "Not Found") });
    const refused = await threadsApi.accept("kv 42", "t1", "m1").catch((e: unknown) => e);
    expect(refused).toBeInstanceOf(ThreadError);
    expect((refused as ThreadError).status).toBe(409);
    expect((refused as ThreadError).message).toBe("Тред уже проверяется");
    await expect(threadsApi.list("kv 42")).rejects.toMatchObject({ status: 404 });
  });
});
