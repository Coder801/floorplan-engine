import { describe, expect, it } from "vitest";
import type { Question } from "@/shared/types";
import { questionCounts } from "./questions";

const q = (id: string, severity: string, state: string): Question =>
  ({ id, stage: "plan", severity, state, text: id, answer: "value" });

describe("questionCounts", () => {
  it("counts unresolved questions by weight, answered ones are left out", () => {
    const counts = questionCounts([
      q("a", "critical", "open"), q("b", "critical", "answered"), q("c", "major", "text"),
      q("d", "minor", "open"), q("e", "minor", "resolved"),
    ]);
    expect(counts).toEqual({ critical: 1, major: 1, minor: 1 });
  });

  it("an unknown weight counts as minor", () => {
    expect(questionCounts([q("a", "info", "open")])).toEqual({ critical: 0, major: 0, minor: 1 });
  });
});
