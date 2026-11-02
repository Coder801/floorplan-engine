import { describe, expect, it } from "vitest";
import { accessCodeChars, formatAccessCode } from "./code";

describe("accessCodeChars", () => {
  it("буквы и цифры заглавными, не больше восьми", () => {
    expect(accessCodeChars("abcd-2345")).toBe("ABCD2345");
    expect(accessCodeChars("код: abcd 2345 67")).toBe("ABCD2345");
    expect(accessCodeChars("--")).toBe("");
  });
});

describe("formatAccessCode", () => {
  it("дефис после четырёх знаков", () => {
    expect(formatAccessCode("abc")).toBe("ABC");
    expect(formatAccessCode("abcd")).toBe("ABCD");
    expect(formatAccessCode("abcd2")).toBe("ABCD-2");
    expect(formatAccessCode("abcd-2345")).toBe("ABCD-2345");
  });
});
