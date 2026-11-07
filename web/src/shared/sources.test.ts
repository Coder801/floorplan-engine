import { describe, expect, it } from "vitest";
import { sourceRows } from "./sources";

describe("sourceRows", () => {
  it("matches a decomposed file name from macOS with the composed one in intake.yaml", () => {
    const nfc = "Дизайн_проєкт.pdf";
    const nfd = nfc.normalize("NFD");
    expect(nfd).not.toBe(nfc);
    expect(sourceRows([nfd], [{ file: nfc, note: "розібрано" }])).toEqual([
      { file: nfd, used: true, note: "розібрано", exists: true }, // the name as on disk
    ]);
  });

  it("tells unused files and parsed files that are gone", () => {
    expect(sourceRows(["a.pdf"], [{ file: "b.pdf", note: "n" }])).toEqual([
      { file: "a.pdf", used: false, note: "", exists: true },
      { file: "b.pdf", used: true, note: "n", exists: false },
    ]);
  });

  it("leaves the status unknown on an old server without parsed", () => {
    expect(sourceRows(["a.pdf"])).toEqual([{ file: "a.pdf", used: null, note: "", exists: true }]);
  });
});
