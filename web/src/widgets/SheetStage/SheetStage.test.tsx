import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { buildDrawing } from "@/engine/sheet/drawing";
import { resetSelection, view } from "@/shared/store";
import { item, page } from "@/shared/testData";
import type { Page, Scene } from "@/shared/types";
import { SheetStage } from "./index";

// The sheet is drawn by its canvas engine (engine/sheet/SheetView, tested on its own): here a
// stand-in that records what the React side asks of it
const sheets: { fit: ReturnType<typeof vi.fn>; zoomTo: ReturnType<typeof vi.fn>;
                setPage: ReturnType<typeof vi.fn>; reveal: ReturnType<typeof vi.fn>;
                destroy: ReturnType<typeof vi.fn>; onZoom: (z: unknown) => void; page: Page }[] = [];
vi.mock("@/engine/sheet/SheetView", () => ({
  SheetView: class {
    fit = vi.fn(); zoomTo = vi.fn(); setPage = vi.fn(); reveal = vi.fn(); destroy = vi.fn();
    onZoom = () => {}; page: Page;
    constructor(_c: unknown, _w: unknown, _d: unknown, p: Page) { this.page = p; sheets.push(this); }
  },
}));
vi.mock("@/widgets/Scene3D", () => ({ Scene3D: () => <div>3D-сцена</div> }));

const wiring = page({ name: "Проводка", stage: "wiring", format: "A3", items: [item("W-CABLE-SOCKET"), item("E-SOCKET")] });
const scene = { ceiling: 2700, assumed: { ceiling: true, openings: ["d1"] }, floors: [], walls: [], wires: {}, points: {}, boxes: {} } as unknown as Scene;

function stage(over: Partial<Parameters<typeof SheetStage>[0]> = {}) {
  const pg = over.page ?? wiring;
  const props = { page: pg, drawing: buildDrawing([pg]), ...over };
  return { ...props, ...render(<SheetStage {...props} />) };
}

beforeEach(() => { resetSelection(); view.set({ show3d: false }); });

describe("SheetStage", () => {
  it("draws the sheet in its canvas; zoom goes both ways", async () => {
    const user = userEvent.setup();
    const { unmount } = stage();
    const sv = sheets.at(-1)!;
    expect(screen.getByLabelText("Чертёж листа")).toBeInTheDocument();
    expect(screen.getByText(/^A3 · колесо — масштаб/)).toBeInTheDocument();
    act(() => sv.onZoom({ step: 1, label: "150%", pxPerMm: 0.2 }));
    await user.click(screen.getByRole("button", { name: "Увеличить" }));
    expect(sv.zoomTo).toHaveBeenCalledWith(2);
    await user.click(screen.getByRole("button", { name: "Весь чертёж" }));
    expect(sv.fit).toHaveBeenCalledOnce();
    unmount();
    expect(sv.destroy).toHaveBeenCalledOnce();
  });

  it("the wiring sheet is view only: no route editing (decision 2026-11-16)", () => {
    stage();
    expect(screen.queryByRole("button", { name: /Править/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Сохранить/ })).toBeNull();
  });

  it("another tab of the same drawing switches the page in the same canvas", () => {
    const { rerender, drawing } = stage();
    const sv = sheets.at(-1)!;
    const lighting = page({ name: "Свет", stage: "lighting", format: "A3", items: [item("E-LIGHT")] });
    rerender(<SheetStage page={lighting} drawing={drawing} />);
    expect(sv.setPage).toHaveBeenCalledWith(lighting, expect.anything());
    expect(sheets.at(-1)).toBe(sv);
  });

  it("the lighting view switches between cables and what switches turn on", async () => {
    const onMode = vi.fn();
    stage({ lightMode: { mode: "wiring", onMode } });
    expect(screen.getByRole("radio", { name: "Кабели" })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: "Что включает" }));
    expect(onMode).toHaveBeenCalledWith("links");
  });

  it("a drawing with a scene turns into 3D, with its hint and wall modes", async () => {
    const user = userEvent.setup();
    stage({ page: { ...wiring, scene } });
    await user.click(screen.getByRole("button", { name: "3D" }));
    expect(await screen.findByText("3D-сцена")).toBeInTheDocument();
    expect(screen.getByText(/потолок 2700 — допущение · высоты проёмов \(1\) — типовые/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Прозрачные" }));
    expect(view.get().wallMode).toBe("ghost");
  });

  it("opens right at the object it was sent to", () => {
    view.set({ goto: { key: "point:s1", stage: "wiring", around: 0.4 } });
    stage();
    expect(sheets.at(-1)!.reveal).toHaveBeenCalledWith("point:s1", 0.4);
    expect(view.get().goto).toBeNull();
  });
});
