import { describe, expect, it } from "vitest";
import { TTL_MS, clearDraft, loadDraft, samePicks, saveDraft } from "./draft";

function memory() {
  const items = new Map<string, string>();
  return {
    items,
    getItem: (k: string) => items.get(k) ?? null,
    setItem: (k: string, v: string) => { items.set(k, v); },
    removeItem: (k: string) => { items.delete(k); },
  };
}
const draft = { picks: { backup: "plug" }, step: "pv" as const };

describe("черновик мастера", () => {
  it("возвращается как был, у каждого проекта свой", () => {
    const s = memory();
    saveDraft("a", 7, draft, s, 1000);
    expect(loadDraft("a", 7, s, 1000 + TTL_MS)).toEqual(draft);
    expect(loadDraft("b", 7, s, 1000)).toBeNull();
  });
  it("живёт 10 минут, потом удаляется", () => {
    const s = memory();
    saveDraft("a", 7, draft, s, 1000);
    expect(loadDraft("a", 7, s, 1001 + TTL_MS)).toBeNull();
    expect(s.items.size).toBe(0);
  });
  it("после пересборки не подхватывается", () => {
    const s = memory();
    saveDraft("a", 7, draft, s, 1000);
    expect(loadDraft("a", 8, s, 1000)).toBeNull();
  });
  it("битая запись и нет хранилища — просто без черновика", () => {
    const s = memory();
    s.items.set("wizard:a", "{oops");
    expect(loadDraft("a", 7, s, 1000)).toBeNull();
    expect(loadDraft("a", 7, null, 1000)).toBeNull();
    saveDraft("a", 7, draft, null);
    clearDraft("a", null);
  });
  it("сравнение выбора: пустое и отсутствующее — одно и то же", () => {
    expect(samePicks({ input: "" }, {})).toBe(true);
    expect(samePicks({ input: "40" }, {})).toBe(false);
  });
});
