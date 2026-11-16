import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { OverviewMaster } from "@/shared/types";
import { MasterList } from "./index";

const master: OverviewMaster = {
  active: false,
  items: [
    { id: "QF1", purpose: "Свет", power: 400, kind: "light", on: true, keep: false },
    { id: "QF2", purpose: "Холодильник", power: 300, kind: "sockets", on: false, keep: true },
    { id: "QF3", purpose: "Розетки", power: 2000, kind: "sockets", on: true, keep: false },
  ],
};

describe("MasterList", () => {
  it("marks loads that keep working and picks groups by hand or by a rule", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<MasterList master={master} value={["QF1", "QF3"]} onChange={onChange} />);
    expect(screen.getByRole("radio", { name: "Всё, кроме постоянных" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /QF2.*работает и без хозяев/ })).not.toBeChecked();
    await user.click(screen.getByRole("radio", { name: "Только свет" }));
    expect(onChange).toHaveBeenLastCalledWith(["QF1"]);
    await user.click(screen.getByRole("checkbox", { name: /QF2/ }));
    expect(onChange).toHaveBeenLastCalledWith(["QF1", "QF2", "QF3"]);
    expect(screen.getByRole("radio", { name: "Вручную" })).toBeChecked();
  });

  it("«don't know» is one more pick with its own note", async () => {
    const onPick = vi.fn();
    const { rerender } = render(<MasterList master={master} value={["QF1"]} onChange={vi.fn()}
                                            unknown={{ on: false, note: "Оставим типовой набор", onPick }} />);
    await userEvent.click(screen.getByRole("radio", { name: "Не знаю" }));
    expect(onPick).toHaveBeenCalledOnce();
    rerender(<MasterList master={master} value={["QF1"]} onChange={vi.fn()} unknown={{ on: true, note: "Оставим типовой набор", onPick }} />);
    expect(screen.getByRole("radio", { name: "Не знаю" })).toBeChecked();
    expect(screen.getByText("Оставим типовой набор")).toBeInTheDocument();
  });
});
