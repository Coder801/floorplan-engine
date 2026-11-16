// The viewer API in component tests (*.test.tsx): fetch is stubbed by a table "METHOD /path" →
// answer, so a widget renders from synthetic data and a test checks which requests a click sent.
// A path is looked up with its query first, then without it. An answer is JSON data, text(…) for
// a plain-text body (getText), fail(status, detail) for an error with the server's reason (detail
// may be an object: a 422 refusal of an answer), or a function of the request body. A JSON body
// is parsed, a multipart one (FormData) is kept as is. A request without an answer fails the test.
// The same idea as admin/src/shared/testApi.ts; the projects share no code.
import { vi } from "vitest";

export class Fail {
  constructor(readonly status: number, readonly detail: unknown) {}
}
export const fail = (status: number, detail: unknown) => new Fail(status, detail);

export class Text {
  constructor(readonly body: string) {}
}
export const text = (body: string) => new Text(body);

type Answer = unknown;
export interface Sent { method: string; path: string; body: unknown }

export function stubApi(routes: Record<string, Answer>): Sent[] {
  const sent: Sent[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: string | URL, init?: RequestInit) => {
    const path = String(input);
    const method = init?.method ?? "GET";
    const raw = init?.body;
    const body = typeof raw === "string" ? JSON.parse(raw) as unknown : raw ?? undefined;
    sent.push({ method, path, body });
    const key = `${method} ${path}`;
    const found = key in routes ? routes[key] : routes[key.split("?")[0]];
    if (found === undefined) throw new Error(`no stub for ${key}`);
    const answer = typeof found === "function" ? (found as (b: unknown) => unknown)(body) : found;
    if (answer instanceof Fail) {
      return new Response(JSON.stringify({ detail: answer.detail }), { status: answer.status, statusText: "Error" });
    }
    if (answer instanceof Text) return new Response(answer.body, { status: 200 });
    return new Response(JSON.stringify(answer), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
  return sent;
}
