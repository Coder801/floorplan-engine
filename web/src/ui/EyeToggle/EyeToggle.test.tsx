import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EyeToggle } from "./index";

describe("EyeToggle", () => {
  it("a visible layer offers to hide it", async () => {
    const onToggle = vi.fn();
    render(<EyeToggle on onToggle={onToggle} what="мебель" />);
    const eye = screen.getByRole("button", { name: "Скрыть: мебель", pressed: true });
    expect(eye).toHaveAttribute("title", "Скрыть: мебель");
    await userEvent.click(eye);
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it("a hidden layer offers to show it", () => {
    render(<EyeToggle on={false} onToggle={() => {}} what="мебель" />);
    expect(screen.getByRole("button", { name: "Показать: мебель", pressed: false })).toBeInTheDocument();
  });

  it("the click does not reach the row under it", () => {
    const onRow = vi.fn();
    render(<div onClick={onRow}><EyeToggle on onToggle={() => {}} what="мебель" /></div>);
    fireEvent.click(screen.getByRole("button"));
    expect(onRow).not.toHaveBeenCalled();
  });

  it("an own label replaces show / hide", () => {
    render(<EyeToggle on onToggle={() => {}} what="QF1" label="Только QF1 на виде" />);
    expect(screen.getByRole("button", { name: "Только QF1 на виде", pressed: true })).toHaveAttribute("title", "Только QF1 на виде");
  });
});
