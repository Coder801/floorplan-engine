import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetSelection, view } from "@/shared/store";
import { BoxScheme } from "./index";
import { boxData, COLORS, manyOuts } from "./mock";

beforeEach(() => resetSelection());

describe("BoxScheme", () => {
  it("draws the feed and a row per cable out: number, where, cable, length; another group shows it", () => {
    const { container } = render(<BoxScheme box={boxData()} colors={COLORS} />);
    const scheme = screen.getByRole("group", { name: "Схема коробки К1: кабелей из неё — 4" });
    expect(within(scheme).getByText("ЩР")).toBeInTheDocument();
    expect(within(scheme).getByText("QF1 · 3x1.5 · 3,9 м")).toBeInTheDocument();
    expect(within(scheme).getByText("Вимикач, Коридор")).toBeInTheDocument();
    expect(within(scheme).getByText("3")).toBeInTheDocument();
    expect(within(scheme).getByText("3x1.5 · 1,6 м")).toBeInTheDocument();
    expect(within(scheme).getByText("QF5 · 3x2.5 · 3 м")).toBeInTheDocument();
    expect(within(scheme).getByText("К2")).toBeInTheDocument();
    expect(container.querySelector("svg text")).toHaveTextContent("К1");
    // The feed and four cables out, in the group colours
    const paths = [...container.querySelectorAll("path")];
    expect(paths).toHaveLength(5);
    expect(paths[0]).toHaveStyle({ stroke: COLORS.QF1 });
    expect(paths[4]).toHaveStyle({ stroke: COLORS.QF5 });
  });

  it("without a feed: says so and draws only the cables out", () => {
    const { container } = render(<BoxScheme box={boxData({ in: null })} />);
    expect(screen.getByText("откуда питание — не указано")).toBeInTheDocument();
    expect(container.querySelectorAll("path")).toHaveLength(4);
    // The box group is then the first cable's: the cable of another group still shows it
    expect(screen.getByText("QF5 · 3x2.5 · 3 м")).toBeInTheDocument();
  });

  it("ten cables out: a row each, a point without a number gets no number", () => {
    render(<BoxScheme box={manyOuts()} />);
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(10);
    expect(rows[7].textContent).toBe("Розетка, Балкон3x1.5 · 6,5 м");
    expect(within(rows[9]).getByText("4")).toBeInTheDocument();
  });

  it("the simple mode: where the cables go, without groups, cables and lengths", () => {
    render(<BoxScheme box={boxData()} brief />);
    expect(screen.getByText("Розетка, Зал")).toBeInTheDocument();
    expect(screen.queryByText(/3x1\.5/)).toBeNull();
    expect(screen.queryByText(/QF/)).toBeNull();
  });

  it("a row under the cursor lights its cable and target, a click opens the target", async () => {
    const onOpen = vi.fn();
    const canOpen = (k: string) => k !== "board";
    const { unmount } = render(<BoxScheme box={boxData()} onOpen={onOpen} canOpen={canOpen} />);
    // The panel cannot be opened: the feed is not a button
    expect(screen.queryByRole("button", { name: /ЩР/ })).toBeNull();
    const next = screen.getByRole("button", { name: /К2/ });
    const user = userEvent.setup();
    await user.hover(next);
    expect(view.get().lit).toEqual(new Set(["wire:wire_9", "box:box_2"]));
    await user.unhover(next);
    expect(view.get().lit).toBeNull();
    await user.click(next);
    expect(onOpen).toHaveBeenCalledWith("box:box_2");
    expect(view.get().lit).toBeNull();
    await user.hover(screen.getByRole("button", { name: /Розетка, Зал/ }));
    unmount();
    expect(view.get().lit).toBeNull();
  });
});
