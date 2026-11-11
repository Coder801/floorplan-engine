import { beforeEach, describe, expect, it, vi } from "vitest";
import { markNoticeSeen, noticeKey, noticeSeen } from "./seen";

// Tests run in Node: an in-memory localStorage
const store = new Map<string, string>();
vi.stubGlobal("localStorage", {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => { store.set(k, v); },
});

describe("stage notice", () => {
  beforeEach(() => store.clear());

  it("is not seen in a fresh browser", () => {
    expect(noticeSeen("alpha")).toBe(false);
  });

  it("is remembered per stage", () => {
    markNoticeSeen("alpha");
    expect(noticeSeen("alpha")).toBe(true);
    expect(noticeSeen("beta")).toBe(false);
    expect(store.get(noticeKey("alpha"))).toBe("seen");
  });
});
