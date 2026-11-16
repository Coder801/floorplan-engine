import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { reserve } from "@/shared/testData";
import { ReserveList } from "./index";

describe("ReserveList", () => {
  it("sums the peak against the source and ticks groups by hand", async () => {
    const onChange = vi.fn();
    render(<ReserveList reserve={reserve()} value={["QF1"]} onChange={onChange} />);
    expect(screen.getByRole("radio", { name: "Только свет" })).toBeChecked();
    expect(screen.getByText(/Пик на резерве 0,4 кВт из 3 кВт/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: /QF2/ }));
    expect(onChange).toHaveBeenCalledWith(["QF1", "QF2"]);
    expect(screen.getByRole("radio", { name: "Вручную" })).toBeChecked();
  });

  it("quick picks: the most the source holds; a sum over the limit warns", async () => {
    const onChange = vi.fn();
    const { rerender } = render(<ReserveList reserve={reserve()} value={["QF1"]} onChange={onChange} />);
    await userEvent.click(screen.getByRole("radio", { name: "Максимум по мощности" }));
    expect(onChange).toHaveBeenLastCalledWith(["QF1", "QF2"]);
    rerender(<ReserveList reserve={reserve()} value={["QF1", "QF2", "QF3"]} onChange={onChange} />);
    expect(screen.getByText(/больше мощности источника/)).toBeInTheDocument();
    expect(screen.getByText(/установлено 5,9 кВт/)).toBeInTheDocument();
  });

  it("without a known source power it says so; disabled it cannot be changed", () => {
    render(<ReserveList reserve={reserve({ limit_kw: null, limit_assumed: true })} value={["QF1"]} disabled onChange={vi.fn()} />);
    expect(screen.getByText(/мощность источника не задана/)).toBeInTheDocument();
    expect(screen.getByText(/мощность — допущение/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /QF1/ })).toBeDisabled();
  });
});
