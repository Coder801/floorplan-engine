import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Card } from "./index";

describe("Card", () => {
  it("is a plain block by default", () => {
    render(<Card>Квартира</Card>);
    expect(screen.getByText("Квартира").tagName).toBe("DIV");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("as a button it is clickable and can be disabled", async () => {
    const onClick = vi.fn();
    const { rerender } = render(<Card as="button" type="button" interactive onClick={onClick}>Открыть проект</Card>);
    await userEvent.click(screen.getByRole("button", { name: "Открыть проект" }));
    expect(onClick).toHaveBeenCalledOnce();
    rerender(<Card as="button" type="button" interactive disabled onClick={onClick}>Открыть проект</Card>);
    expect(screen.getByRole("button")).toBeDisabled();
  });
});
