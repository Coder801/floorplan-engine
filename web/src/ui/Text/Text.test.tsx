import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Text } from "./index";

describe("Text", () => {
  it("is a paragraph by default and another element with as", () => {
    render(<><Text>Абзац</Text><Text as="span" role="status" id="n">Сохранено</Text></>);
    expect(screen.getByText("Абзац").tagName).toBe("P");
    const status = screen.getByRole("status");
    expect(status.tagName).toBe("SPAN");
    expect(status).toHaveAttribute("id", "n");
  });
});
