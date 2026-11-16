// The admin API in component tests: fetch is stubbed by a table "METHOD /path" → answer, so a
// page renders from synthetic data and a test checks which requests a click sent. A path is
// looked up with its query first, then without it. fail(409, "…") answers with an error and the
// server's reason; a function gets the request body. A request without an answer fails the test.
import { vi } from "vitest";

export class Fail {
  constructor(readonly status: number, readonly detail: string) {}
}
export const fail = (status: number, detail: string) => new Fail(status, detail);

type Answer = unknown | ((body: unknown) => unknown);
export interface Sent { method: string; path: string; body: unknown }

export function stubApi(routes: Record<string, Answer>): Sent[] {
  const sent: Sent[] = [];
  vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) as unknown : undefined;
    sent.push({ method, path, body });
    const key = `${method} ${path}`;
    const found = key in routes ? routes[key] : routes[key.split("?")[0]];
    if (found === undefined) throw new Error(`no stub for ${key}`);
    const answer = typeof found === "function" ? (found as (b: unknown) => unknown)(body) : found;
    if (answer instanceof Fail) return new Response(JSON.stringify({ detail: answer.detail }), { status: answer.status });
    return new Response(JSON.stringify(answer), { status: 200 });
  }));
  return sent;
}
