import { beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_REPORT, pdfName, rememberReport, reportUrl, savedReport } from "./report";

// Before the imports: i18n (through api.ts) reads the language from localStorage on load
const store = vi.hoisted(() => {
  const m = new Map<string, string>();
  globalThis.localStorage = {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => { m.set(k, v); },
  } as Storage;
  return m;
});

describe("reportUrl", () => {
  it("lists the parts in the page order, whatever the click order", () => {
    expect(reportUrl("p1", ["work_finish", "plan", "material_rough"], "landscape"))
      .toBe("/api/projects/p1/result?parts=plan,material_rough,work_finish&orientation=landscape");
  });

  it("encodes the project key and passes the orientation", () => {
    expect(reportUrl("кв 42/a", ["plan"], "portrait"))
      .toBe(`/api/projects/${encodeURIComponent("кв 42/a")}/result?parts=plan&orientation=portrait`);
  });

  it("drops repeats", () => {
    expect(reportUrl("p1", ["plan", "plan"], "portrait")).toBe("/api/projects/p1/result?parts=plan&orientation=portrait");
  });

  it("the PDF of the same report", () => {
    expect(reportUrl("p1", ["panel"], "landscape", true)).toBe("/api/projects/p1/result.pdf?parts=panel&orientation=landscape");
  });
});

describe("pdfName", () => {
  it("takes the UTF-8 name over the plain one, report.pdf without a header", () => {
    const name = "Кв 42 — Смета электрики.pdf";
    expect(pdfName(`attachment; filename="report.pdf"; filename*=UTF-8''${encodeURIComponent(name)}`)).toBe(name);
    expect(pdfName('attachment; filename="plan.pdf"')).toBe("plan.pdf");
    expect(pdfName("attachment; filename*=UTF-8''%E0%A4%A")).toBe("report.pdf");
    expect(pdfName(null)).toBe("report.pdf");
  });
});

describe("saved report options", () => {
  beforeEach(() => store.clear());

  it("defaults to all parts, portrait", () => {
    expect(savedReport()).toEqual(DEFAULT_REPORT);
  });

  it("remembers the choice and cleans a broken one", () => {
    rememberReport({ parts: ["work_rough", "plan"], orientation: "landscape" });
    expect(savedReport()).toEqual({ parts: ["plan", "work_rough"], orientation: "landscape" });
    store.set("report-options", JSON.stringify({ parts: ["nope"], orientation: "sideways" }));
    expect(savedReport()).toEqual(DEFAULT_REPORT);
    store.set("report-options", "{");
    expect(savedReport()).toEqual(DEFAULT_REPORT);
  });
});
