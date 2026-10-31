import { describe, expect, it } from "vitest";
import { codeDigits, secondsLeft } from "./code";

describe("codeDigits", () => {
  it("только цифры, не больше шести", () => {
    expect(codeDigits("123 456")).toBe("123456");
    expect(codeDigits("код: 12-34-5678")).toBe("123456");
    expect(codeDigits("abc")).toBe("");
  });
});

describe("secondsLeft", () => {
  it("округляет вверх и не уходит в минус", () => {
    expect(secondsLeft(10_500, 10_000)).toBe(1);
    expect(secondsLeft(70_000, 10_000)).toBe(60);
    expect(secondsLeft(5_000, 10_000)).toBe(0);
  });
});
