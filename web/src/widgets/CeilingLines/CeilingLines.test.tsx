import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { resetSelection, view } from "@/shared/store";
import type { CeilingData, CeilingLine } from "@/shared/types";
import { CeilingLines } from "./index";

const line = (run: string, group: string, from: string, source: string, to: string, target: string,
  over: Partial<CeilingLine> = {}): CeilingLine => ({
  key: `lane:bed.ceiling.${run}`, group, color: group === "QF1" ? "#d0662a" : null,
  from, to, source, target, transit: false, mark: "3x1.5", length: 1000, ...over,
});

// QF1: ЩР → К1, К1 → 8, К1 → К2, К2 → 12; QF3: one line ЩР → 31; QF4: passes through
const lines = [
  line("w1", "QF1", "ЩР", "board", "К1", "box_1"),
  line("w2", "QF1", "К1", "box_1", "8 · Выключатель", "s8", { length: 1100 }),
  line("w3", "QF1", "К1", "box_1", "К2", "box_2"),
  line("w4", "QF1", "К2", "box_2", "12 · Светильник", "l12"),
  line("w5", "QF3", "ЩР", "board", "31 · Розетка", "s31", { mark: "3x2.5", length: 2430 }),
  line("w6", "QF4", "ЩР", "board", "К8", "box_8", { transit: true }),
];
const ceiling = (over: Partial<CeilingData> = {}): CeilingData =>
  ({ key: "elevation:bed.ceiling", plane: "ceiling", lines, ...over });

beforeEach(() => resetSelection());

describe("CeilingLines", () => {
  it("groups the lines by panel group with the cable summary; transit groups last", () => {
    render(<CeilingLines ceiling={ceiling()} />);
    expect(screen.getByRole("heading", { name: /Линии на потолке/ })).toHaveTextContent("6");
    expect(screen.getByText("3x1.5 — 5,1 м · 3x2.5 — 2,4 м")).toBeInTheDocument();
    const rows = screen.getAllByRole("listitem");
    expect(rows.map((r) => r.querySelector("span:nth-child(2)")?.textContent)).toEqual(["QF1", "QF3", "QF4"]);
    expect(rows[0]).toHaveTextContent("линий: 4 · 4,1 м");
    expect(rows[1]).toHaveTextContent("ЩР → 31 · Розетка");  // one line: the row itself, no chevron
    expect(rows[1]).toHaveTextContent("3x2.5 · 2,4 м");
    expect(within(rows[2]).getByText("транзит")).toBeInTheDocument();
    expect(screen.queryByText("На проводке →")).toBeNull();
  });

  it("an open group is its chain: the feed, then box by box, the line to the next box last", async () => {
    const user = userEvent.setup();
    render(<CeilingLines ceiling={ceiling()} />);
    await user.click(screen.getByRole("button", { name: "Раскрыть QF1" }));
    const rows = screen.getAllByRole("listitem").map((r) => r.textContent);
    expect(rows.slice(1, 7)).toEqual(["ЩР → К11,0 м", "К1", "├8 · Выключатель1,1 м", "└→ К21,0 м", "К2", "└12 · Светильник1,0 м"]);
    // Hover: the group lights all its lanes, a box its lines, a line its lane; a click pins
    await user.hover(screen.getByText("К1", { selector: "span" }));
    expect(view.get().lit).toEqual(new Set(["lane:bed.ceiling.w2", "lane:bed.ceiling.w3"]));
    const row = screen.getByText("8 · Выключатель").closest("li")!;
    await user.hover(row);
    expect(view.get().lit).toEqual(new Set(["lane:bed.ceiling.w2"]));
    await user.click(row);
    expect(view.get().pinned).toBe("lane:bed.ceiling.w2");
    expect(screen.getByText("ЩР → К1 → 8 · Выключатель")).toBeInTheDocument();  // the route card
  });

  it("a group eye hides the group on the view, the header eye hides or shows them all", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<CeilingLines ceiling={ceiling()} />);
    await user.click(screen.getByRole("button", { name: "Скрыть: QF3" }));
    expect(view.get().filter3d.groups).toEqual(new Set(["QF1", "QF4"]));
    expect(view.get().selected).toBeNull();  // the others are not dimmed
    expect(screen.getByRole("button", { name: "Показать: QF3" }).closest("li")).toHaveClass(/off/);
    // Something hidden: the header eye shows all again
    await user.click(screen.getByRole("button", { name: "Показать все линии" }));
    expect(view.get().filter3d.groups).toBeNull();
    await user.click(screen.getByRole("button", { name: "Скрыть все линии на виде" }));
    expect(view.get().filter3d.groups).toEqual(new Set());
    unmount();
    expect(view.get().filter3d.groups).toBeNull();  // leaving the view shows every group again
  });

  it("a line pinned on the view opens its group", () => {
    render(<CeilingLines ceiling={ceiling()} />);
    expect(screen.queryByText("12 · Светильник")).toBeNull();
    act(() => view.set({ pinned: "lane:bed.ceiling.w4" }));
    expect(screen.getByText("12 · Светильник").closest("li")).toHaveClass(/lit/);
    expect(screen.getByText("ЩР → К1 → К2 → 12 · Светильник")).toBeInTheDocument();
  });

  it("an older .epd without ids chains by names", async () => {
    const old = lines.map(({ source: _s, target: _t, transit: _x, ...rest }) => rest);
    render(<CeilingLines ceiling={ceiling({ lines: old })} />);
    await userEvent.click(screen.getByRole("button", { name: "Раскрыть QF1" }));
    expect(screen.getByText("→ К2")).toBeInTheDocument();
    expect(screen.queryByText("транзит")).toBeNull();
  });

  it("the floor view and an empty view", () => {
    render(<CeilingLines ceiling={ceiling({ plane: "floor", lines: [] })} />);
    expect(screen.getByRole("heading", { name: /Линии по полу/ })).toBeInTheDocument();
    expect(screen.getByText("Линий нет")).toBeInTheDocument();
  });
});
