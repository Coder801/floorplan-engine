import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { project, question } from "@/shared/testData";
import type { Project, Variants, VariantSummary } from "@/shared/types";
import { Wizard } from "./index";

// The panel part only: two questions of the report, no wiring variants
const panel = (over: Partial<Project> = {}) => project({
  report: {
    questions: [
      question({ id: "panel_phases", stage: "panel", answer: "choice", options: ["1", "3"], assumption: 1, unit: undefined }),
      question({ id: "panel_input", stage: "panel", answer: "value", assumption: 63, unit: "A" }),
      question({ id: "q9", stage: "plan", text: "Где щит?", answer: "text" }),
    ],
    issues: [],
  },
  ...over,
});

function open(p: Project, over: Partial<Parameters<typeof Wizard>[0]> = {}) {
  const props = {
    project: p, variants: null, ceiling: null, reserve: null,
    onApply: vi.fn().mockResolvedValue(true), onClose: vi.fn(), onQuestions: vi.fn(), ...over,
  };
  return { ...props, ...render(<Wizard {...props} />) };
}

describe("Wizard", () => {
  it("walks the steps, says what changes and sends all the answers at once", async () => {
    const user = userEvent.setup();
    const { onApply } = open(panel());
    expect(screen.getByRole("dialog", { name: "Настройка проекта" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Сколько фаз на вводе?" })).toBeInTheDocument();
    expect(screen.getByText("Шаг 1 из 3")).toBeInTheDocument();
    expect(screen.getByText("Обязательный шаг: влияет на цену")).toBeInTheDocument();
    const recalc = screen.getByRole("button", { name: "Пересчитать" });
    expect(recalc).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Назад" })).toBeNull();

    const cards = screen.getByRole("radiogroup", { name: "Сколько фаз на вводе?" });
    expect(within(cards).getByRole("radio", { name: /Одна фаза.*сейчас в проекте/ })).not.toBeChecked();
    await user.click(within(cards).getByRole("radio", { name: /Три фазы/ }));
    expect(within(cards).getByRole("radio", { name: /Три фазы/ })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Дальше" }));

    expect(screen.getByRole("heading", { level: 1, name: "Какой вводной автомат?" })).toBeInTheDocument();
    // a required step without an answer keeps "Recalculate" off and says which one
    expect(screen.getByText(/Осталось: Вводной автомат/)).toBeInTheDocument();
    expect(recalc).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "50" }));
    await user.click(screen.getByRole("button", { name: "Дальше" }));

    expect(screen.getByRole("heading", { level: 1, name: "Проверьте и пересчитайте" })).toBeInTheDocument();
    expect(screen.getByText("Три фазы, 400 В")).toBeInTheDocument();
    expect(screen.getAllByText("изменится")).toHaveLength(2);
    expect(screen.getByText(/Других открытых вопросов: 1/)).toBeInTheDocument();
    expect(recalc).toBeEnabled();
    await user.click(recalc);
    expect(onApply).toHaveBeenCalledWith({ answers: { panel_phases: 3, panel_input: 50 } });
  });

  it("a number out of rule is marked and blocks the step", async () => {
    const user = userEvent.setup();
    open(panel(), { start: "input" });
    const field = screen.getByRole("textbox", { name: /Номинал/ });
    await user.type(field, "50.5");
    expect(field).toBeInvalid();
    expect(screen.getByText("Нужно целое число ампер больше нуля")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Дальше" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Пересчитать" })).toBeDisabled();
  });

  it("the step list moves to a step; back returns", async () => {
    const user = userEvent.setup();
    open(panel());
    const steps = screen.getByRole("navigation", { name: "Шаги настройки" });
    await user.click(within(steps).getByRole("button", { name: /Вводной автомат/ }));
    expect(within(steps).getByRole("button", { name: /Вводной автомат/ })).toHaveAttribute("aria-current", "step");
    await user.click(screen.getByRole("button", { name: "Назад" }));
    expect(screen.getByRole("heading", { level: 1, name: "Сколько фаз на вводе?" })).toBeInTheDocument();
  });

  it("an unapplied choice survives closing and can be reset", async () => {
    const user = userEvent.setup();
    const first = open(panel());
    await user.click(screen.getByRole("radio", { name: /Три фазы/ }));
    first.unmount();
    open(panel());
    expect(screen.getByText(/Восстановлен выбор, который вы не применили/)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Три фазы/ })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Сбросить" }));
    expect(screen.getByRole("radio", { name: /Три фазы/ })).not.toBeChecked();
    expect(screen.queryByText(/Восстановлен выбор/)).toBeNull();
  });

  it("shows the server's refusal and keeps the choice", async () => {
    const user = userEvent.setup();
    open(panel({ answers: { panel_input: 63 } }), { onApply: vi.fn().mockRejectedValue(new Error("422: вводной меньше групп")) });
    await user.click(screen.getByRole("radio", { name: /Три фазы/ }));
    await user.click(screen.getByRole("button", { name: "Пересчитать" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не сохранено — 422: вводной меньше групп");
    expect(screen.getByRole("radio", { name: /Три фазы/ })).toBeChecked();
  });

  it("Esc and × close it after the fade", async () => {
    const user = userEvent.setup();
    const { onClose } = open(panel());
    await user.keyboard("{Escape}");
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    await user.click(screen.getByRole("button", { name: "Закрыть" }));
    await new Promise((r) => setTimeout(r, 200));
    expect(onClose).toHaveBeenCalledOnce();  // closing already: once
  });

  it("with wiring variants it asks the wiring first and shows prices of the computed choices", async () => {
    const user = userEvent.setup();
    const item = (mode: string, route: string, total: number) =>
      ({ key: `${mode}-${route}-boxes`, mode, route, distribution: "boxes", total, currency: "грн", cable_m: 120, chases_m: 30 }) as VariantSummary;
    const variants: Variants = {
      active: "standard-ceiling-boxes", default: "standard-ceiling-boxes",
      items: ["economy", "standard", "proper"].flatMap((m, k) => [item(m, "ceiling", 10000 + k), item(m, "floor", 20000 + k)]),
    };
    open(project(), { variants, ceiling: { height: 2700, assumed: true } });
    expect(screen.getByRole("heading", { level: 1, name: "Как вести кабель?" })).toBeInTheDocument();
    const steps = screen.getByRole("navigation", { name: "Шаги настройки" });
    expect(within(steps).getByText("Проводка")).toBeInTheDocument();
    expect(within(steps).getByText("Дополнительные опции")).toBeInTheDocument();
    await user.click(within(steps).getByRole("button", { name: "Итог" }));
    expect(screen.getByText("Изменений нет.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Пересчитать" })).toBeDisabled();
  });
});
