import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { overview, project, question, variants } from "@/shared/testData";
import { OverviewStage, OverviewSummary } from "./index";

function open(over: Partial<Parameters<typeof OverviewStage>[0]> = {}) {
  const props = {
    overview: overview(), variants: variants(), project: project({ sources: ["a.pdf", "b.jpg"], parsed: [{ file: "a.pdf", note: "" }] }),
    openQuestions: 2, canChoose: true, onEstimate: vi.fn(), onDrawer: vi.fn(), onWizard: vi.fn(), ...over,
  };
  return { ...props, ...render(<OverviewStage {...props} />) };
}

describe("OverviewStage", () => {
  it("shows the object, rooms and the ceiling assumption", () => {
    open();
    expect(screen.getByRole("heading", { level: 1, name: "Общие сведения" })).toBeInTheDocument();
    expect(screen.getByText("ул. Нагорная, 16")).toBeInTheDocument();
    expect(screen.queryByText("Организация")).toBeNull();  // empty facts are skipped
    expect(screen.getByText(/2\s700 мм/)).toHaveTextContent("допущение: в плане не указана");
    const kitchen = screen.getByRole("row", { name: /Кухня/ });
    expect(kitchen).toHaveTextContent("мокрое");
    expect(kitchen).toHaveTextContent("12,5");
  });

  it("the wiring variant, its neighbours with the difference, and the project total", async () => {
    const { onEstimate } = open({ overview: overview({ plumbing: {
      fixtures: [{ type: "wc", text: "Унитаз", count: 1 }],
      water: { distribution: "collector", hot: "boiler", cold_m: 12.5, hot_m: 8, outlets: 4, input_assumed: false },
      sewer: { pipes: [{ d: 110, m: 3.2 }], risers: 1, bends: 2, tees: 1, errors: 1 }, weak: 2,
      estimate: { total: 15000, material: 10000, work: 5000, currency: "грн", unpriced: 3 },
    } }) });
    expect(screen.getByRole("heading", { name: "Вариант проводки" })).toBeInTheDocument();
    const floor = screen.getByRole("row", { name: /Трасса кабеля:.*по полу/ });
    expect(floor).toHaveTextContent(/−3\s000 грн/);
    expect(screen.getByRole("row", { name: /Ваш набор/ })).toHaveTextContent("как в проекте");
    expect(screen.getByRole("row", { name: /по потолку|подрозетник/i })).toBeInTheDocument();
    expect(screen.getByText(/Ø110 — 3,2 м/)).toBeInTheDocument();
    expect(screen.getByText(/трасс с ошибкой: 1/)).toBeInTheDocument();
    expect(screen.getByText(/без цены: 3 поз./)).toBeInTheDocument();
    const total = screen.getByRole("heading", { level: 2, name: /Итог по проекту/ }).closest("section")!;
    expect(total).toHaveTextContent(/65\s000 грн/);
    expect(total).toHaveTextContent(/электрика \(выбранный вариант\) 50\s000 грн · сантехника 15\s000 грн/);
    expect(total).toHaveTextContent(/Работа\s*25\s000 грн/);
    expect(total).toHaveTextContent(/Материалы\s*40\s000 грн/);
    expect(within(total).queryByRole("img")).toBeNull();  // studio prices: no provisional mark
    await userEvent.click(within(total).getByRole("button", { name: "Открыть смету" }));
    expect(onEstimate).toHaveBeenCalledOnce();
  });

  it("what is planned: points and the panel line", () => {
    open({ overview: overview({
      points: [{ key: "socket", text: "Розетки", count: 24, unit: "шт" }],
      panel: { scheme: "standard", phases: 3, input: "C25", input_assumed: false, devices: 18, groups: 12, modules: 36, installed_w: 12500, calculated_w: 8000 },
    }) });
    expect(screen.getByRole("row", { name: /Розетки/ })).toHaveTextContent("24 шт");
    expect(screen.getByText(/3 фазы, ввод C25, аппаратов 18, групп 12/)).toBeInTheDocument();
    expect(screen.getByText("нагрузка: установленная 12.5 кВт, расчётная 8 кВт")).toBeInTheDocument();
  });

  it("the setup note names what is left and opens the wizard; questions and sources open the drawer", async () => {
    const user = userEvent.setup();
    const { onWizard, onDrawer } = open({ setup: { total: 5, open: ["route", "plaster", "rough", "labels"], steps: [], declined: [] } });
    expect(screen.getByText(/Не решено 4 из 5: трасса кабеля, .*и ещё 1/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Настроить проект" }));
    expect(onWizard).toHaveBeenCalledOnce();
    expect(screen.getByText(/Файлов: 2, разобрано: 1\. Открытых вопросов: 2/)).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Исходники" })[0]);
    expect(onDrawer).toHaveBeenCalledWith("sources");
  });

  it("a rebuild keeps the blocks busy; no overview says to rebuild", () => {
    const { container, unmount } = open({ refreshing: true });
    expect(container.firstElementChild).toHaveAttribute("aria-busy", "true");
    unmount();
    open({ overview: null });
    expect(screen.getByText(/Общих сведений нет/)).toBeInTheDocument();
  });
});

describe("OverviewSummary", () => {
  it("lists the setup steps: an open one opens the wizard on it, a declined one is struck", async () => {
    const user = userEvent.setup();
    const onWizard = vi.fn(), onDrawer = vi.fn();
    render(<OverviewSummary setup={{ total: 3, open: ["route"], steps: ["route", "rough", "labels"], declined: ["rough"] }}
                            questions={[question({ severity: "critical" }), question({ id: "q2", severity: "minor" })]}
                            onWizard={onWizard} onDrawer={onDrawer} />);
    expect(screen.getByRole("img", { name: "не решено" })).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: "решено" })).toHaveLength(2);
    expect(screen.getByText("Решено 2 из 3")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Трасса кабеля" }));
    expect(onWizard).toHaveBeenCalledWith("route");
    await user.click(screen.getByRole("button", { name: "Настроить проект" }));
    expect(onWizard).toHaveBeenLastCalledWith();
    expect(screen.getAllByText("1", { selector: "dd" })).toHaveLength(2);  // critical and minor
    await user.click(screen.getByRole("button", { name: "Вопросы" }));
    expect(onDrawer).toHaveBeenCalledWith("questions");
  });

  it("all decided and no questions; read only without the wizard", () => {
    render(<OverviewSummary setup={{ total: 1, open: [], steps: ["route"], declined: [] }} questions={[]} onDrawer={vi.fn()} />);
    expect(screen.getByText("Всё решено: смета и щит — по вашим ответам")).toBeInTheDocument();
    expect(screen.getByText("Открытых вопросов нет")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Настроить проект" })).toBeNull();
  });
});
