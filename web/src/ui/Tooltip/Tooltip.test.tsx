import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DELAY_MS, useTooltip } from "./index";

function Bar() {
  const tooltip = useTooltip();
  return (
    <>
      <button {...tooltip.on("Сохранить правки")}>Сохранить</button>
      {tooltip.tip}
    </>
  );
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useTooltip", () => {
  it("opens after the mouse stays on the button for DELAY_MS and describes it", () => {
    render(<Bar />);
    const button = screen.getByRole("button", { name: "Сохранить" });
    fireEvent.pointerEnter(button, { pointerType: "mouse" });
    act(() => vi.advanceTimersByTime(DELAY_MS - 1));
    expect(screen.queryByRole("tooltip")).toBeNull();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Сохранить правки");
    expect(button).toHaveAccessibleDescription("Сохранить правки");
  });

  it("closes when the pointer leaves or presses", () => {
    render(<Bar />);
    const button = screen.getByRole("button");
    fireEvent.pointerEnter(button, { pointerType: "mouse" });
    act(() => vi.advanceTimersByTime(DELAY_MS));
    fireEvent.pointerDown(button);
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.pointerEnter(button, { pointerType: "mouse" });
    fireEvent.pointerLeave(button);
    act(() => vi.advanceTimersByTime(DELAY_MS));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("does not open on touch", () => {
    render(<Bar />);
    fireEvent.pointerEnter(screen.getByRole("button"), { pointerType: "touch" });
    act(() => vi.advanceTimersByTime(DELAY_MS));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});
