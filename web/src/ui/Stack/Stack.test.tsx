import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Stack } from "./index";

describe("Stack", () => {
  it("lays children out with the gap of the spacing grid, as the given element", () => {
    render(<Stack as="ul" gap={4} aria-label="Шаги"><li>Один</li><li>Два</li></Stack>);
    const list = screen.getByRole("list", { name: "Шаги" });
    expect(list).toHaveStyle({ gap: "var(--space-4)" });
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("gap 0 means no space", () => {
    render(<Stack gap={0} data-testid="s">x</Stack>);
    expect(screen.getByTestId("s")).toHaveStyle({ gap: "0px" });
  });
});
