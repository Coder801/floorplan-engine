import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HOLD_MS, useHoldTip } from "./index";

function Row() {
  const hold = useHoldTip();
  return (
    <>
      <div onPointerEnter={(e) => hold.start("Линия 3: кухня", e)} onPointerMove={hold.move} onPointerLeave={hold.stop}>строка</div>
      {hold.tip}
    </>
  );
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useHoldTip", () => {
  it("shows the tooltip only after the pointer stays for HOLD_MS", () => {
    render(<Row />);
    fireEvent.pointerEnter(screen.getByText("строка"), { clientX: 10, clientY: 20 });
    act(() => vi.advanceTimersByTime(HOLD_MS - 1));
    expect(screen.queryByRole("tooltip")).toBeNull();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Линия 3: кухня");
  });

  it("passing over the row shows nothing; leaving hides a shown one", () => {
    render(<Row />);
    const row = screen.getByText("строка");
    fireEvent.pointerEnter(row);
    fireEvent.pointerLeave(row);
    act(() => vi.advanceTimersByTime(HOLD_MS));
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.pointerEnter(row);
    act(() => vi.advanceTimersByTime(HOLD_MS));
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    fireEvent.pointerLeave(row);
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});
