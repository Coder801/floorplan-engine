import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MenuItem } from "./index";

describe("MenuItem", () => {
  it("is a menu item button that calls onClick, the note sits beside the label", async () => {
    const onClick = vi.fn();
    render(<MenuItem note="Ctrl+P" onClick={onClick}>Печать</MenuItem>);
    const item = screen.getByRole("menuitem");
    expect(item).toHaveTextContent("ПечатьCtrl+P");
    await userEvent.click(item);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("with href is a download link, but a disabled one is a disabled button", () => {
    const { rerender } = render(<MenuItem href="/out/project.dxf" download="project.dxf">DXF</MenuItem>);
    expect(screen.getByRole("menuitem", { name: "DXF" })).toHaveAttribute("download", "project.dxf");
    rerender(<MenuItem href="/out/project.dxf" disabled>DXF</MenuItem>);
    const item = screen.getByRole("menuitem", { name: "DXF" });
    expect(item.tagName).toBe("BUTTON");
    expect(item).toBeDisabled();
  });

  it("marks the chosen option or radio item", () => {
    render(
      <>
        <MenuItem role="option" selected>Русский</MenuItem>
        <MenuItem role="option">English</MenuItem>
        <MenuItem role="menuitemradio" selected>Тёмная</MenuItem>
      </>,
    );
    expect(screen.getByRole("option", { name: "Русский" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("option", { name: "English" })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("menuitemradio", { name: "Тёмная" })).toBeChecked();
  });
});
