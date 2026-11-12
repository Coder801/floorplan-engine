import { describe, expect, it } from "vitest";
import { agentOf, applyChange, authorOf, contextOf, nextStatus } from "./feedback";
import { ago, contact, date, who } from "./format";
import { href, parse } from "./route";

describe("route", () => {
  it("reads the section, the record and the filter from the hash", () => {
    expect(parse("#/studios/abc")).toMatchObject({ section: "studios", id: "abc" });
    expect(parse("#/events?project=p1").params.get("project")).toBe("p1");
    expect(parse("")).toMatchObject({ section: "summary", id: null });
    expect(parse("#/nope/1").section).toBe("summary");
    expect(parse("#/feedback?status=new")).toMatchObject({ section: "feedback", id: null });
  });
  it("writes what it reads", () => {
    const h = href("projects", "a b", { tab: "codes" });
    expect(parse(h)).toMatchObject({ section: "projects", id: "a b" });
    expect(parse(h).params.get("tab")).toBe("codes");
  });
});

describe("format", () => {
  it("shows dates and how long ago", () => {
    expect(date(null)).toBe("—");
    expect(date("2026-11-03T10:05:00", false)).toBe("03.11.2026");
    const now = new Date("2026-11-03T12:00:00").getTime();
    expect(ago("2026-11-03T11:30:00", now)).toBe("30 мин");
    expect(ago("2026-11-01T12:00:00", now)).toBe("2 дн");
  });
  it("does not break on a bad date and keeps old dates as dates", () => {
    expect(date("вчера")).toBe("—");
    expect(ago("вчера")).toBe("—");
    expect(ago(null)).toBe("—");
    const now = new Date("2026-11-03T12:00:00").getTime();
    expect(ago("2026-11-03T11:59:30", now)).toBe("сейчас");
    expect(ago("2026-11-03T09:00:00", now)).toBe("3 ч");
    expect(ago("2026-09-01T12:00:00", now)).toBe("01.09.2026");
  });
  it("names a person by what is known", () => {
    expect(who({ name: "", email: null, phone: "+380" })).toBe("+380");
    expect(who(null)).toBe("—");
    expect(who({ name: "", email: null, phone: null })).toBe("без имени");
    expect(contact({ email: "a@b.c", phone: null })).toBe("a@b.c");
    expect(contact({ email: "a@b.c", phone: "+380" })).toBe("a@b.c · +380");
    expect(contact({ email: null, phone: null })).toBe("—");
  });
});

describe("feedback", () => {
  const item = (id: string, status: "new" | "seen" | "done") => ({
    id, status, created_at: null, kind: "bug" as const, text: "т", admin_note: null, context: null, author: null, project: null, photos: [],
  });
  it("moves new → seen → done and stops", () => {
    expect(nextStatus("new")).toBe("seen");
    expect(nextStatus("seen")).toBe("done");
    expect(nextStatus("done")).toBeNull();
  });
  it("names the author by what is known", () => {
    expect(authorOf(null)).toBe("—");
    expect(authorOf({ name: "Иван", email: "i@x" })).toBe("Иван");
    expect(authorOf({ email: "i@x" })).toBe("i@x");
    expect(authorOf({ code_label: "Петров" })).toBe("код «Петров»");
    expect(authorOf({})).toBe("—");
  });
  it("shows the context in a fixed order without empty values", () => {
    expect(contextOf(null)).toEqual([]);
    expect(contextOf({ path: "/#kv", sheet: "plan", version: "", viewport: "1440×900", user_agent: "UA" }))
      .toEqual(["лист: plan", "экран: 1440×900", "адрес: /#kv"]);
    expect(agentOf({ user_agent: "UA" })).toBe("UA");
    expect(agentOf({ user_agent: 5 })).toBe("");
    expect(agentOf(null)).toBe("");
  });
  it("puts a changed item back and moves the counts", () => {
    const page = { items: [item("a", "new"), item("b", "new")], total: 2, counts: { new: 2, seen: 0, done: 1 } };
    const next = applyChange(page, { ...item("a", "seen"), admin_note: "смотрю" });
    expect(next.items.map((i) => i.status)).toEqual(["seen", "new"]);
    expect(next.items[0].admin_note).toBe("смотрю");
    expect(next.counts).toEqual({ new: 1, seen: 1, done: 1 });
    expect(page.counts.new).toBe(2);  // the old page is not changed
    // A note only: the counts stay
    expect(applyChange(page, { ...item("b", "new"), admin_note: "x" }).counts).toEqual(page.counts);
  });
});
