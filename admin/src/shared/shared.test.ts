import { describe, expect, it } from "vitest";
import { ago, contact, date, who } from "./format";
import { href, parse } from "./route";

describe("route", () => {
  it("reads the section, the record and the filter from the hash", () => {
    expect(parse("#/studios/abc")).toMatchObject({ section: "studios", id: "abc" });
    expect(parse("#/events?project=p1").params.get("project")).toBe("p1");
    expect(parse("")).toMatchObject({ section: "summary", id: null });
    expect(parse("#/nope/1").section).toBe("summary");
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
  it("names a person by what is known", () => {
    expect(who({ name: "", email: null, phone: "+380" })).toBe("+380");
    expect(contact({ email: "a@b.c", phone: null })).toBe("a@b.c");
  });
});
