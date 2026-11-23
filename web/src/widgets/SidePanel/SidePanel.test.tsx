import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { buildDrawing } from "@/engine/sheet/drawing";
import { resetSelection, view } from "@/shared/store";
import { item, page } from "@/shared/testData";
import type { Page, SideTable } from "@/shared/types";
import { SidePanel, hasLayers } from "./index";

beforeEach(() => {
  resetSelection();
  view.set({ hidden: new Set(), extra: new Set(), cables: true, filter3d: { groups: null, room: null } });
});

const groups: SideTable = {
  title: "Группы", columns: ["Группа", "Автомат", "кВт"], align: ["left", "center", "right"],
  rows: [
    { cells: ["QF1", "C16", "2,0"], keys: ["line:QF1"], group: "QF1", color: "#d00000", hint: "Розетки кухни" },
    { cells: ["QF2", "C10", "0,4"], keys: ["line:QF2"], group: "QF2" },
    { cells: ["Вводной", "C40", ""], marker: "square" },
  ],
  total: ["Итого", "", "2,4"],
  notes: ["Нагрузки — по проекту"],
};

function panel(over: Partial<Parameters<typeof SidePanel>[0]> = {}) {
  const p: Page = over.page ?? page({ tables: [groups] });
  const props = { tab: "tables" as const, onTab: vi.fn(), page: p, drawing: p ? buildDrawing([p]) : null, ...over };
  return { ...props, ...render(<SidePanel {...props} />) };
}

describe("SidePanel", () => {
  it("shows the tables and layers tabs only where the sheet has layers", async () => {
    const { onTab } = panel();
    const tabs = screen.getByRole("tablist");
    expect(within(tabs).getByRole("tab", { name: "Таблицы" })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(within(tabs).getByRole("tab", { name: "Слои" }));
    expect(onTab).toHaveBeenCalledWith("layers");
    expect(hasLayers(page({ items: [item("A-SHEET")] }))).toBe(false);
    expect(hasLayers(null)).toBe(false);
  });

  it("a row lights its objects on hover and selects its line on click; the total and notes follow", async () => {
    const user = userEvent.setup();
    panel();
    expect(screen.getByRole("heading", { name: "Группы" })).toBeInTheDocument();
    const qf1 = screen.getByRole("row", { name: /QF1/ });
    await user.hover(qf1);
    expect(view.get().lit).toEqual(new Set(["line:QF1"]));
    await user.unhover(qf1);
    expect(view.get().lit).toBeNull();
    await user.click(within(qf1).getByText("C16"));
    expect(view.get().selected).toEqual(new Set(["line:QF1"]));
    expect(screen.getByRole("row", { name: /Итого/ })).toHaveTextContent("2,4");
    expect(screen.getByText("Нагрузки — по проекту")).toBeInTheDocument();
  });

  it("the eye of a group hides it from the drawing and 3D; all on again means no filter", async () => {
    const user = userEvent.setup();
    panel();
    await user.click(screen.getByRole("button", { name: "Скрыть: QF1" }));
    expect(view.get().filter3d.groups).toEqual(new Set(["QF2"]));
    expect(view.get().selected).toBeNull();
    await user.click(screen.getByRole("button", { name: "Показать: QF1" }));
    expect(view.get().filter3d.groups).toBeNull();
  });

  it("a row held under the pointer shows its hint", () => {
    vi.useFakeTimers();
    panel();
    fireEvent.pointerEnter(screen.getByRole("row", { name: /QF1/ }));
    vi.advanceTimersByTime(2000);
    return vi.waitFor(() => expect(screen.getByRole("tooltip")).toHaveTextContent("Розетки кухни"));
  });

  it("says when there is no sheet or no tables; the simple mode has a short note for wiring", () => {
    const { unmount } = panel({ page: null, drawing: null });
    expect(screen.getByText("Лист не открыт")).toBeInTheDocument();
    unmount();
    const second = panel({ page: page() });
    expect(screen.getByText("У этого листа таблиц нет")).toBeInTheDocument();
    second.unmount();
    view.set({ cables: false });
    panel({ page: page({ stage: "wiring", tables: [groups] }) });
    expect(screen.getByText(/Линии показывают, где пойдёт кабель/)).toBeInTheDocument();
  });

  it("the layers tab switches the sheet's own layers off and adds others", async () => {
    const user = userEvent.setup();
    panel({ tab: "layers" });
    expect(screen.getByText("Точки и выводы")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Скрыть: розетки" }));
    expect(view.get().hidden).toEqual(new Set(["E-SOCKET"]));
    await user.click(screen.getByText("розетки"));
    expect(view.get().hidden).toEqual(new Set());
    await user.click(screen.getByRole("button", { name: "Скрыть: Помещение" }));
    expect(view.get().hidden).toEqual(new Set(["A-WALL"]));
  });

  it("the estimate tab shows section totals and the wiring variant line", async () => {
    const onOpen = vi.fn();
    panel({
      estimate: {
        title: "Смета", columns: ["", "Позиция", "Сумма"], align: ["left", "left", "right"],
        rows: [{ cells: ["", "Работы — цены условные", ""], section: true }, { cells: ["1", "Штроба", "100"] }, { cells: ["", "Итого", "100"] },
               { cells: ["", "Материалы", ""], section: true }, { cells: ["2", "Кабель", "50"] }, { cells: ["", "Итого", "50"], guess: true }],
        total: ["", "Всего", "150"], notes: ["Без материалов"],
      },
      variant: { label: "Стандарт, по потолку", onOpen },
    });
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.getByText("Работы")).toBeInTheDocument();
    expect(screen.getByText("Всего")).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: "Цена условная: материалы пока не по рыночным ценам" }).map((x) => x.parentElement!.textContent)).toEqual(["50!"]);
    expect(screen.getByText("Без материалов")).toBeInTheDocument();
    expect(screen.getByText("Стандарт, по потолку")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "изменить" }));
    expect(onOpen).toHaveBeenCalledOnce();
  });

  it("a ceiling page: its lines, the sheet tables on the notes tab", async () => {
    const ceiling = { key: "elevation:bed.ceiling", plane: "ceiling" as const, lines: [
      { key: "lane:bed.ceiling.wire_1", group: "QF1", color: null, from: "ЩР", to: "К1", source: "board", target: "box_1",
        transit: false, mark: "3x2.5", length: 1200 },
    ] };
    const { onTab, rerender, ...props } = panel({ tab: "tables", ceiling });
    const tabs = screen.getByRole("tablist");
    expect(within(tabs).getAllByRole("tab").map((x) => x.textContent)).toEqual(["Линии", "Памятка", "Слои"]);
    expect(within(tabs).getByRole("tab", { name: "Линии" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: /Линии на потолке/ })).toBeInTheDocument();
    expect(screen.getByText(/ЩР → К1/)).toBeInTheDocument();
    expect(screen.queryByText("Группы")).toBeNull();  // the installer tables are on their own tab
    await userEvent.click(within(tabs).getByRole("tab", { name: "Памятка" }));
    expect(onTab).toHaveBeenCalledWith("notes");
    rerender(<SidePanel {...props} onTab={onTab} ceiling={ceiling} tab="notes" />);
    expect(screen.getByText("Группы")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Линии на потолке/ })).toBeNull();
  });

  it("a summary replaces tables and layers; the bottom drawer folds on a phone", async () => {
    panel({ summary: <p>Сводка проекта</p>, summaryTitle: "План работ" });
    expect(screen.getByText("Сводка проекта")).toBeInTheDocument();
    expect(screen.getByText("План работ")).toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "Таблицы и слои" });
    await userEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Свернуть" })).toHaveAttribute("aria-expanded", "true");
  });
});
