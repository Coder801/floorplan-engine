import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Checkbox } from "./index";

describe("Checkbox", () => {
  it("passes the new state, the label is clickable", async () => {
    const onChange = vi.fn();
    render(<Checkbox checked={false} onChange={onChange} label="Розетки" note="12 точек" />);
    const box = screen.getByRole("checkbox", { name: /Розетки/ });
    expect(box).not.toBeChecked();
    await userEvent.click(screen.getByText("Розетки"));
    expect(onChange).toHaveBeenCalledWith(true);
    expect(screen.getByText("12 точек")).toBeInTheDocument();
  });

  it("unchecks a checked one", async () => {
    const onChange = vi.fn();
    render(<Checkbox checked onChange={onChange} label="Свет" />);
    expect(screen.getByRole("checkbox")).toBeChecked();
    await userEvent.click(screen.getByRole("checkbox"));
    expect(onChange).toHaveBeenCalledWith(false);
  });

  it("does not change when disabled", async () => {
    const onChange = vi.fn();
    render(<Checkbox checked={false} onChange={onChange} label="Свет" disabled />);
    expect(screen.getByRole("checkbox")).toBeDisabled();
    await userEvent.click(screen.getByText("Свет"));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("shows some of them as indeterminate; without a label it takes aria-label", () => {
    const { rerender } = render(<Checkbox checked={false} onChange={() => {}} aria-label="Все группы" indeterminate />);
    expect(screen.getByRole("checkbox", { name: "Все группы" })).toBePartiallyChecked();
    rerender(<Checkbox checked={false} onChange={() => {}} aria-label="Все группы" />);
    expect(screen.getByRole("checkbox")).not.toBePartiallyChecked();
  });
});
