import { describe, expect, it } from "vitest";
import { base, isProject } from "./api";

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
