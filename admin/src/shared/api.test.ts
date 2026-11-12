import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, addStudioMember, events, feedback, me, setActive, updateFeedback, users } from "./api";

const fetched = vi.fn<typeof fetch>();

function answer(status: number, body: unknown, statusText = "") {
  fetched.mockResolvedValueOnce(new Response(body === undefined ? "сбой" : JSON.stringify(body), { status, statusText }));
  vi.stubGlobal("fetch", fetched);
}

afterEach(() => {
  fetched.mockReset();
  vi.unstubAllGlobals();
});

describe("api", () => {
  it("sends no body and no header on a read", async () => {
    answer(200, { auth: true });
    await expect(me()).resolves.toEqual({ auth: true });
    expect(fetched).toHaveBeenCalledWith("/api/auth/me", { method: "GET", headers: undefined, body: undefined });
  });
  it("sends JSON on a write and escapes ids in the path", async () => {
    answer(200, {});
    await addStudioMember("a/b", "u@x", "designer");
    const [path, init] = fetched.mock.calls[0];
    expect(path).toBe("/api/admin/studios/a%2Fb/members");
    expect(init).toMatchObject({ method: "POST", headers: { "Content-Type": "application/json" } });
    expect(JSON.parse(String(init?.body))).toEqual({ user: "u@x", role: "designer" });
  });
  it("keeps a false value in the body", async () => {
    answer(200, {});
    await setActive("u1", false);
    expect(JSON.parse(String(fetched.mock.calls[0][1]?.body))).toEqual({ active: false });
  });
  it("escapes the search and builds the event filter", async () => {
    answer(200, []);
    await users("a&b");
    expect(fetched.mock.calls[0][0]).toBe("/api/admin/users?q=a%26b");
    answer(200, []);
    await events({ project: "p1" });
    expect(fetched.mock.calls[1][0]).toBe("/api/admin/events?project=p1&limit=200");
  });
  it("throws the server's reason, status included", async () => {
    answer(409, { detail: "последний владелец" });
    const error = await me().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, message: "последний владелец" });
  });
  it("shows a validation list as text and survives an answer that is not JSON", async () => {
    answer(422, { detail: [{ loc: ["body"] }] });
    await expect(me()).rejects.toThrow('[{"loc":["body"]}]');
    answer(502, undefined, "Bad Gateway");
    await expect(me()).rejects.toMatchObject({ status: 502, message: "Bad Gateway" });
  });
  it("builds the feedback filter without empty fields and sends a change", async () => {
    answer(200, { items: [], total: 0, counts: { new: 0, seen: 0, done: 0 } });
    await feedback();
    expect(fetched.mock.calls[0][0]).toBe("/api/admin/feedback?offset=0&limit=50");
    answer(200, { items: [], total: 0, counts: { new: 0, seen: 0, done: 0 } });
    await feedback({ status: "new", kind: "", q: "не жмёт", offset: 50, limit: 25 });
    expect(fetched.mock.calls[1][0]).toBe("/api/admin/feedback?status=new&q=%D0%BD%D0%B5+%D0%B6%D0%BC%D1%91%D1%82&offset=50&limit=25");
    answer(200, {});
    await updateFeedback("f/1", { status: "seen", admin_note: "" });
    const [path, init] = fetched.mock.calls[2];
    expect(path).toBe("/api/admin/feedback/f%2F1");
    expect(init).toMatchObject({ method: "PATCH" });
    expect(JSON.parse(String(init?.body))).toEqual({ status: "seen", admin_note: "" });
  });
});
