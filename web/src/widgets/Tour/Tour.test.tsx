import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Tour, type TourFacts } from "./index";

// jsdom has no layout: an anchor gets a box unless it is marked hidden (display: none in a browser)
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    const on = !this.hasAttribute("data-hidden");
    return { left: 100, top: 10, width: on ? 120 : 0, height: on ? 36 : 0, right: 220, bottom: 46, x: 100, y: 10, toJSON: () => ({}) } as DOMRect;
  });
});
afterEach(() => vi.restoreAllMocks());

const facts = (over: Partial<TourFacts> = {}): TourFacts =>
  ({ sheets: true, canAnswer: true, openQuestions: 2, canChoose: true, setupTotal: 3, ...over });

// The screen the tour points at: the anchors of pages/Viewer and widgets/OverviewStage
function Screen({ hide = [] }: { hide?: string[] }) {
  const mark = (key: string) => ({ "data-tour": key, ...(hide.includes(key) ? { "data-hidden": "" } : {}) });
  return (
    <>
      <nav {...mark("sheets")}>Листы</nav>
      <button {...mark("questions")}>Вопросы</button>
      <button {...mark("questions-menu")}>⋯</button>
      <button {...mark("help")}>?</button>
      <div {...mark("overview")}>Общие сведения</div>
      <button {...mark("setup")}>Настроить проект</button>
      <button {...mark("setup-page")}>Настроить проект</button>
    </>
  );
}

describe("Tour", () => {
  it("goes through the five steps: counter, «Дальше», «Понятно» on the last one", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<><Screen /><Tour facts={facts()} onClose={onClose} /></>);
    const titles = ["Это ваш проект", "Смотрите чертёж", "Ответьте на вопросы", "Настройте проект", "Подсказки — здесь"];
    for (const [i, title] of titles.entries()) {
      expect(screen.getByRole("dialog", { name: title })).toBeInTheDocument();
      expect(screen.getByText(`${i + 1} из 5`)).toBeInTheDocument();
      if (i < titles.length - 1) {
        expect(screen.getByRole("button", { name: "Дальше" })).toHaveFocus();
        await user.click(screen.getByRole("button", { name: "Дальше" }));
      }
    }
    expect(screen.queryByRole("button", { name: "Пропустить" })).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Понятно" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("the sheets step says how to zoom with a mouse", async () => {
    const user = userEvent.setup();
    render(<><Screen /><Tour facts={facts()} onClose={() => {}} /></>);
    await user.click(screen.getByRole("button", { name: "Дальше" }));
    expect(screen.getByText("Колесо — масштаб, перетаскивание — сдвиг.")).toBeInTheDocument();
  });

  it("drops the steps without the right or without their anchor and counts the rest", async () => {
    const user = userEvent.setup();
    render(<><Screen hide={["sheets"]} /><Tour facts={facts({ openQuestions: 0, canChoose: false })} onClose={() => {}} /></>);
    expect(screen.getByRole("dialog", { name: "Это ваш проект" })).toBeInTheDocument();
    expect(screen.getByText("1 из 2")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Дальше" }));
    expect(screen.getByRole("dialog", { name: "Подсказки — здесь" })).toBeInTheDocument();
    expect(screen.getByText("2 из 2")).toBeInTheDocument();
  });

  it("on a phone the questions are behind «⋯»", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("innerWidth", 400);
    render(<><Screen /><Tour facts={facts()} onClose={() => {}} /></>);
    await user.click(screen.getByRole("button", { name: "Дальше" }));
    await user.click(screen.getByRole("button", { name: "Дальше" }));
    expect(screen.getByRole("dialog", { name: "Ответьте на вопросы" })).toHaveTextContent(/^.*Вопросы — в меню «⋯»\. Студии нужны/);
  });

  it("«Пропустить» and Esc close it on any step", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const { unmount } = render(<><Screen /><Tour facts={facts()} onClose={onClose} /></>);
    await user.click(screen.getByRole("button", { name: "Пропустить" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    unmount();
    render(<><Screen /><Tour facts={facts()} onClose={onClose} /></>);
    await user.click(screen.getByRole("button", { name: "Дальше" }));
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("Tab stays inside the card", async () => {
    const user = userEvent.setup();
    render(<><Screen /><Tour facts={facts()} onClose={() => {}} /></>);
    expect(screen.getByRole("button", { name: "Дальше" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Пропустить" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Дальше" })).toHaveFocus();
  });

  it("no anchor at all: closes right away", () => {
    const onClose = vi.fn();
    render(<Tour facts={facts()} onClose={onClose} />);
    expect(onClose).toHaveBeenCalledOnce();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
