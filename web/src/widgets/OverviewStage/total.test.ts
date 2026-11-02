import { describe, expect, it } from "vitest";
import type { VariantSummary } from "@/shared/types";
import { projectTotal } from "./total";

const variant = { total: 1000, currency: "грн", unpriced: 1 } as VariantSummary;

describe("projectTotal", () => {
  it("складывает электрику выбранного варианта и сантехнику", () => {
    expect(projectTotal(variant, { total: 250.5, currency: "грн", unpriced: 2 })).toEqual({
      total: 1250.5, currency: "грн", electrical: 1000, plumbing: 250.5, unpriced: 3,
    });
  });
  it("одна смета — итог по ней, без второй части", () => {
    expect(projectTotal(variant)).toMatchObject({ total: 1000, plumbing: undefined });
    expect(projectTotal(undefined, { total: 80, currency: "грн", unpriced: 0 })).toMatchObject({
      total: 80, currency: "грн", electrical: undefined,
    });
  });
  it("смет нет — итога нет", () => {
    expect(projectTotal()).toBeNull();
  });
});
