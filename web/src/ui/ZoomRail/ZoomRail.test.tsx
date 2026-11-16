import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LAST_STEP, zoomLabel } from "@/shared/zoom";
import { ZoomRail } from "./index";

const zoom = (step: number) => ({ step, label: zoomLabel(step), pxPerMm: 0.1 });

describe("ZoomRail", () => {
  it("+ and − go one step, fit calls onFit", async () => {
    const onStep = vi.fn(), onFit = vi.fn();
    render(<ZoomRail zoom={zoom(2)} onStep={onStep} onFit={onFit} fitLabel="Весь лист" />);
    expect(screen.getByRole("group", { name: "Масштаб" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Увеличить" }));
    expect(onStep).toHaveBeenLastCalledWith(3);
    await userEvent.click(screen.getByRole("button", { name: "Уменьшить" }));
    expect(onStep).toHaveBeenLastCalledWith(1);
    await userEvent.click(screen.getByRole("button", { name: "Весь лист" }));
    expect(onFit).toHaveBeenCalledOnce();
  });

  it("the ends disable their button", () => {
    const { rerender } = render(<ZoomRail zoom={zoom(0)} onStep={() => {}} onFit={() => {}} fitLabel="Весь лист" />);
    expect(screen.getByRole("button", { name: "Уменьшить" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Увеличить" })).toBeEnabled();
    rerender(<ZoomRail zoom={zoom(LAST_STEP)} onStep={() => {}} onFit={() => {}} fitLabel="Весь лист" />);
    expect(screen.getByRole("button", { name: "Увеличить" })).toBeDisabled();
  });

  it("the slider says the step and moves by the keyboard", async () => {
    const user = userEvent.setup();
    const onStep = vi.fn();
    render(<ZoomRail zoom={zoom(1)} onStep={onStep} onFit={() => {}} fitLabel="Весь лист" />);
    const slider = screen.getByRole("slider");
    expect(slider).toHaveAttribute("aria-valuenow", "1");
    expect(slider).toHaveAttribute("aria-valuetext", "150%");
    slider.focus();
    await user.keyboard("{ArrowUp}");
    expect(onStep).toHaveBeenLastCalledWith(2);
    await user.keyboard("{ArrowLeft}");
    expect(onStep).toHaveBeenLastCalledWith(0);
    await user.keyboard("{End}");
    expect(onStep).toHaveBeenLastCalledWith(LAST_STEP);
    await user.keyboard("{Home}");
    expect(onStep).toHaveBeenLastCalledWith(0);
  });
});
