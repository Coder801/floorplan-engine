import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ButtonGroup, GroupButton } from "./index";

describe("ButtonGroup", () => {
  it("is a named group of buttons", () => {
    render(<ButtonGroup label="Вид"><GroupButton>2D</GroupButton><GroupButton>3D</GroupButton></ButtonGroup>);
    const group = screen.getByRole("group", { name: "Вид" });
    expect(group).toContainElement(screen.getByRole("button", { name: "2D" }));
    expect(group).toContainElement(screen.getByRole("button", { name: "3D" }));
  });

  it("an entry calls onClick, is a toggle only with pressed and hides its badge from screen readers", async () => {
    const onClick = vi.fn();
    render(<GroupButton pressed badge={3} aria-label="Правки: 3" onClick={onClick}>Правки</GroupButton>);
    const button = screen.getByRole("button", { name: "Правки: 3", pressed: true });
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveTextContent("Правки3");
    await userEvent.click(button);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("draws no badge for null or false", () => {
    const { rerender } = render(<GroupButton badge={null}>Слои</GroupButton>);
    expect(screen.getByRole("button")).toHaveTextContent(/^Слои$/);
    rerender(<GroupButton badge={false}>Слои</GroupButton>);
    expect(screen.getByRole("button")).toHaveTextContent(/^Слои$/);
    expect(screen.getByRole("button")).not.toHaveAttribute("aria-pressed");
  });
});
