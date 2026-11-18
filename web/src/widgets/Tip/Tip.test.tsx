import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PageIndex } from "@/shared/page";
import { resetSelection, view } from "@/shared/store";
import { page } from "@/shared/testData";
import { boxData } from "@/widgets/BoxScheme/mock";
import { Tip } from "./index";

const index = new PageIndex(page({
  stage: "wiring",
  objects: {
    "point:s1": { title: "Розетка 3", rows: [["Группа", "QF4"]], block: { posts: 1, x: 400, y: 300, wall: "elevation:k.w1" } },
    "box:b1": { title: "Коробка К1", rows: [["Типоразмер", "100×100"]], box: boxData(), brief: { title: "Коробка К1", rows: [] } },
    "box:b2": { title: "Коробка К2", rows: [["Типоразмер", "100×100"]] },
    "point:p3": { title: "Вимикач", rows: [] },
    "wire:w1": { title: "Линия QF4", rows: [["Кабель", "3×2,5"], ["Длина", "12 м"]], brief: { title: "Линия QF4", rows: [["Откуда", "щит"]] } },
  },
}));

beforeEach(() => { resetSelection(); view.set({ cables: true }); });

describe("Tip", () => {
  it("follows the cursor with the card of the object under it", () => {
    const { container } = render(<div><Tip index={index} /></div>);
    expect(container.firstElementChild).toBeEmptyDOMElement();
    act(() => view.set({ tip: { key: "wire:w1", x: 20, y: 30 } }));
    expect(screen.getByText("Линия QF4")).toBeInTheDocument();
    expect(screen.getByText("3×2,5")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("the simple mode shows the short card of a line", () => {
    view.set({ cables: false, tip: { key: "wire:w1", x: 0, y: 0 } });
    render(<Tip index={index} />);
    expect(screen.getByText("щит")).toBeInTheDocument();
    expect(screen.queryByText("3×2,5")).toBeNull();
  });

  it("pinned: the socket frame and a way to its wall; × and Esc unpin", async () => {
    const onWall = vi.fn();
    view.set({ pinned: "point:s1", selected: new Set(["point:s1"]) });
    render(<Tip index={index} onWall={onWall} />);
    expect(screen.getByRole("img", { name: /Блок: постов 1/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Развёртка стены" }));
    expect(onWall).toHaveBeenCalledWith("elevation:k.w1");
    await userEvent.click(screen.getByRole("button", { name: "Закрыть подсказку" }));
    expect(view.get()).toMatchObject({ pinned: null, selected: null });
    act(() => view.set({ pinned: "point:s1" }));
    await userEvent.keyboard("{Escape}");
    expect(view.get().pinned).toBeNull();
  });

  it("pinned box: the scheme of its cables, a row opens its target; hovered — only the card", async () => {
    view.set({ tip: { key: "box:b1", x: 0, y: 0 } });
    render(<Tip index={index} />);
    expect(screen.getByText("Коробка К1")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /Схема коробки/ })).toBeNull();
    act(() => view.set({ pinned: "box:b1" }));
    expect(screen.getByRole("group", { name: "Схема коробки К1: кабелей из неё — 4" })).toBeInTheDocument();
    expect(screen.getByText("3x1.5 · 1,6 м")).toBeInTheDocument();
    // The point is on this sheet, the next box К2 is not
    expect(screen.queryByRole("button", { name: /К2/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Вимикач, Коридор/ }));
    expect(view.get().pinned).toBe("point:p3");
    expect(view.get().selected).toEqual(new Set(["point:p3"]));
  });

  it("the simple mode: the box scheme without cables and lengths", () => {
    view.set({ cables: false, pinned: "box:b1" });
    render(<Tip index={index} />);
    expect(screen.getByText("Вимикач, Коридор")).toBeInTheDocument();
    expect(screen.queryByText(/3x1\.5/)).toBeNull();
  });

  it("a box of an older build: the card as before, no scheme", () => {
    view.set({ pinned: "box:b2" });
    render(<Tip index={index} />);
    expect(screen.getByText("100×100")).toBeInTheDocument();
    expect(screen.queryByRole("group")).toBeNull();
  });

  it("an unknown object gets its kind and id", () => {
    view.set({ tip: { key: "box:K3", x: 0, y: 0 } });
    render(<Tip index={index} />);
    expect(screen.getByText(/· K3/)).toBeInTheDocument();
  });
});
