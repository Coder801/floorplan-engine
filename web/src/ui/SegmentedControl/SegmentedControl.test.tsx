import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SegmentedControl, type Segment } from "./index";

const OPTIONS: Segment<"plan" | "electrical" | "wiring">[] = [
  { value: "plan", label: "План" },
  { value: "electrical", label: "Электрика", title: "Розетки и выключатели" },
  { value: "wiring", label: "3", ariaLabel: "Проводка: 3 правки", disabled: true },
];

describe("SegmentedControl", () => {
  it("is a radio group with the current choice checked", () => {
    render(<SegmentedControl label="Лист" options={OPTIONS} value="plan" onChange={() => {}} />);
    expect(screen.getByRole("radiogroup", { name: "Лист" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "План" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Электрика" })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: "Электрика" })).toHaveAttribute("title", "Розетки и выключатели");
  });

  it("a click passes the value; a disabled segment cannot be chosen", async () => {
    const onChange = vi.fn();
    render(<SegmentedControl label="Лист" options={OPTIONS} value={null} onChange={onChange} />);
    expect(screen.queryByRole("radio", { checked: true })).toBeNull();
    await userEvent.click(screen.getByRole("radio", { name: "Электрика" }));
    expect(onChange).toHaveBeenCalledWith("electrical");
    const wiring = screen.getByRole("radio", { name: "Проводка: 3 правки" });
    expect(wiring).toBeDisabled();
    await userEvent.click(wiring);
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});
