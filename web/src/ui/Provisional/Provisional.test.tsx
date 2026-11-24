import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Provisional } from "./index";

describe("Provisional", () => {
  it("shows the value with a warning triangle named by the reason, the reason is also the tooltip", () => {
    render(<p>Материалы <Provisional label="Цена условная">40 000 грн</Provisional></p>);
    const sign = screen.getByRole("img", { name: "Цена условная" });
    expect(sign.tagName).toBe("svg");
    const value = sign.parentElement!;
    expect(value).toHaveTextContent("40 000 грн");
    expect(value).toHaveAttribute("title", "Цена условная");
  });
});
