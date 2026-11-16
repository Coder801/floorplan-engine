import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { resetSelection, view } from "@/shared/store";
import { page } from "@/shared/testData";
import type { PanelData, PanelDevice } from "@/shared/types";
import { DeviceCard } from "./index";

const device = (over: Partial<PanelDevice>): PanelDevice => ({
  id: "QF4", key: "device:QF4", kind: "breaker", label: "C16", title: "Автомат", group: "QF4",
  model: { id: "generic.breaker", brand: "generic", series: "", modules: 1, width: 18, height: 85, style: "breaker", body: "" } as PanelDevice["model"],
  ...over,
});

const panel = {
  name: "ЩР", phases: 1, scheme: "standard", input: { label: "C40", assumed: false },
  devices: [device({}), device({ id: "QF9", key: "device:QF9", group: "QF9", reserve: true, model: { ...device({}).model, brand: "ABB", series: "S200" } })],
  groups: {
    QF4: { purpose: "Розетки кухни", purpose_assumed: true, cable: "3×2,5", power: 2000, current: 9, assumed: false, loads: 2, color: "#d00000", split_of: null },
    QF9: { purpose: "Свет", purpose_assumed: false, cable: "3×1,5", power: 300, current: 1, assumed: false, loads: 1, color: null, split_of: "QF8" },
  },
  totals: { installed: 0, demand: 0, calculated: 0, current: 0, modules: 0 },
  warnings: [{ severity: "major", text: "Длинная линия", group: "QF4" }],
  texts: { title: "", grid: "", reserve: "" },
} as unknown as PanelData;

const sheet = page({
  stage: "panel",
  tables: [
    { title: "Аппараты", columns: ["", "Аппарат", "Кабель"], align: [], rows: [{ cells: ["QF4", "C16", "3×2,5"], keys: ["device:QF4"] }] },
    { title: "Потребители", columns: [], align: [], rows: [{ cells: ["1", "Чайник", "кухня", "2000"], keys: ["device:QF4"] }] },
  ],
});

beforeEach(() => resetSelection());

describe("DeviceCard", () => {
  it("shows the pinned device: purpose, table row, model, bus, loads and weak spots", () => {
    view.set({ pinned: "device:QF4" });
    render(<DeviceCard page={sheet} panel={panel} />);
    const card = screen.getByRole("dialog", { name: "Аппарат QF4" });
    expect(card).toHaveTextContent("Розетки кухни*");
    expect(card).toHaveTextContent("Кабель3×2,5");
    expect(card).toHaveTextContent("типовая · 1 мод. · 18×85 мм");
    expect(card).toHaveTextContent("основная");
    expect(screen.getByRole("heading", { name: "Потребители · 1" })).toBeInTheDocument();
    expect(card).toHaveTextContent("Чайник");
    expect(card).toHaveTextContent("2000 Вт");
    expect(screen.getByText("Длинная линия")).toBeInTheDocument();
  });

  it("a split line on the backup bus, with its brand", () => {
    view.set({ pinned: "device:QF9" });
    render(<DeviceCard page={sheet} panel={panel} />);
    const card = screen.getByRole("dialog");
    expect(card).toHaveTextContent("ABB S200");
    expect(card).toHaveTextContent("резервная");
    expect(card).toHaveTextContent("часть QF8 — перегруз разделён на щите");
  });

  it("closes by the cross and by Esc; nothing is shown without a pinned device", async () => {
    view.set({ pinned: "device:QF4" });
    render(<DeviceCard page={sheet} panel={panel} />);
    await userEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    act(() => view.set({ pinned: "device:QF4" }));
    await userEvent.keyboard("{Escape}");
    expect(view.get().pinned).toBeNull();
  });
});
