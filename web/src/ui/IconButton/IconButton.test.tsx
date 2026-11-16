import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { IconButton } from "./index";

describe("IconButton", () => {
  it("is named by its label, which is also the tooltip", async () => {
    const onClick = vi.fn();
    render(<IconButton label="Меню" onClick={onClick}><svg /></IconButton>);
    const button = screen.getByRole("button", { name: "Меню" });
    expect(button).toHaveAttribute("title", "Меню");
    expect(button).toHaveAttribute("type", "button");
    await userEvent.click(button);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("an explicit title wins over the label", () => {
    render(<IconButton label="Закрыть" title="Закрыть (Esc)" variant="close" />);
    const button = screen.getByRole("button", { name: "Закрыть" });
    expect(button).toHaveAttribute("title", "Закрыть (Esc)");
    expect(button).toHaveTextContent("×");
  });

  it("is a toggle only with pressed and does not react when disabled", async () => {
    const onClick = vi.fn();
    const { rerender } = render(<IconButton label="Слои" onClick={onClick} />);
    expect(screen.getByRole("button")).not.toHaveAttribute("aria-pressed");
    rerender(<IconButton label="Слои" pressed disabled onClick={onClick} />);
    expect(screen.getByRole("button", { pressed: true })).toBeDisabled();
    await userEvent.click(screen.getByRole("button"));
    expect(onClick).not.toHaveBeenCalled();
  });
});
