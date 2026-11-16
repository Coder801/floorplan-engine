import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { page, reserve } from "@/shared/testData";
import type { PanelData } from "@/shared/types";
import { PanelStage } from "./index";

// The panel front is drawn by its canvas engine (engine/panel, tested on its own)
const views: { zoomTo: ReturnType<typeof vi.fn>; fit: ReturnType<typeof vi.fn>; destroy: ReturnType<typeof vi.fn>; onZoom?: (z: unknown) => void }[] = [];
vi.mock("@/engine/panel/PanelView", () => ({
  PanelView: class {
    zoomTo = vi.fn(); fit = vi.fn(); destroy = vi.fn(); onZoom?: (z: unknown) => void;
    constructor() { views.push(this); }
  },
}));

const panel = {
  name: "ЩР", phases: 1, scheme: "standard", input: { label: "C40", assumed: true }, devices: [], groups: {},
  totals: { installed: 5400, demand: 0, calculated: 3200, current: 16, modules: 24 },
  warnings: [{ severity: "major", text: "Длинная линия", group: null }, { severity: "minor", text: "Мелочь", group: null }],
  texts: { title: "", grid: "", reserve: "" },
  stickers: {
    width: 18, height: 12, pad: 1, rule_y: 6, band: "", icon: { x: 0, y: 0, size: 4, stroke: 0.3 }, icons: {},
    items: [{ id: "QF1", row: 0, title: "Свет", icon: "x", number: "", name: "", short_id: "1", short_number: "M0 0", color: "#000", on_color: "#fff" }],
  },
} as unknown as PanelData;

function stage(over: Partial<Parameters<typeof PanelStage>[0]> = {}) {
  const props = { page: page({ stage: "panel" }), panel, mode: "front" as const, onMode: vi.fn(), reserve: reserve(),
    reserveEditable: true, busy: false, onReserve: vi.fn().mockResolvedValue(undefined), ...over };
  return { ...props, ...render(<PanelStage {...props} />) };
}

describe("PanelStage", () => {
  it("the front: canvas, totals with weak spots, zoom; the modes the build has data for", async () => {
    const user = userEvent.setup();
    const { onMode } = stage();
    const v = views.at(-1)!;
    expect(screen.getByLabelText("Щит в лицо")).toBeInTheDocument();
    expect(screen.getByText(/5,40 кВт установлено · 3,20 кВт \/ 16 А расчётно · ввод C40\* · слабых мест: 1/)).toBeInTheDocument();
    act(() => v.onZoom?.({ step: 2, label: "200%", pxPerMm: 1 }));
    await user.click(screen.getByRole("button", { name: "Уменьшить" }));
    expect(v.zoomTo).toHaveBeenCalledWith(1);
    expect(screen.getByRole("radio", { name: "Щит" })).toBeChecked();
    await user.click(screen.getByRole("radio", { name: "Маркировка" }));
    expect(onMode).toHaveBeenCalledWith("stickers");
  });

  it("stickers and backup modes replace the canvas", () => {
    const { unmount } = stage({ mode: "stickers" });
    expect(screen.getByRole("heading", { level: 1, name: "Маркировка" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Щит в лицо")).toBeNull();
    unmount();
    stage({ mode: "reserve" });
    expect(screen.getByRole("heading", { level: 1, name: "Что держать на резерве" })).toBeInTheDocument();
  });

  it("no stickers or backup in the build — no switch", () => {
    stage({ panel: { ...panel, stickers: undefined }, reserve: undefined });
    expect(screen.queryByRole("radiogroup", { name: "Вид щита" })).toBeNull();
  });
});
