import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { stubApi } from "@/shared/testApi";
import type { WorkRun } from "@/shared/work";
import { draftState, INSTALLER, workState } from "@/widgets/WorkStage/mock";
import { WorkBoard } from "./index";

// A run that sends the request to the stubbed API, like useWork does
const live = (): WorkRun => vi.fn(async (call) => { await call("p1"); return true; });

// jsdom has no DataTransfer: a stub with what the tile touches
const dataTransfer = () => ({ setData: vi.fn(), effectAllowed: "", dropEffect: "" });
const column = (name: string) => screen.getByRole("region", { name });
const tile = (col: string, name: RegExp) => within(column(col)).getByRole("button", { name });
const drag = (from: HTMLElement, to: HTMLElement) => {
  fireEvent.dragStart(from, { dataTransfer: dataTransfer() });
  fireEvent.dragOver(to, { dataTransfer: dataTransfer() });
};

describe("WorkBoard", () => {
  it("shows the approved plan with progress and tasks by status; a tile opens its card", async () => {
    const onOpen = vi.fn();
    render(<WorkBoard state={workState()} run={live()} busy={false} open="cable" onOpen={onOpen} />);
    expect(screen.getByRole("heading", { level: 1, name: "Работы по плану" })).toBeInTheDocument();
    expect(screen.getByText("Утверждён")).toBeInTheDocument();
    expect(screen.getByText("Утверждён студией за заказчика — по звонку: звонок 2.11, Андрей")).toBeInTheDocument();
    expect(screen.getByText("Принято 1 из 7")).toBeInTheDocument();
    const review = screen.getByRole("region", { name: "На приёмке" });
    expect(within(review).getByRole("button", { name: /Распаечные коробки/ })).toBeInTheDocument();
    const returned = screen.getByRole("region", { name: "Возвращено" });
    const cable = within(returned).getByRole("button", { name: /Прокладка кабеля/ });
    expect(cable).toHaveAttribute("aria-pressed", "true");
    expect(cable).toHaveTextContent("фото: 1");
    const todo = screen.getByRole("region", { name: "К работе" });
    expect(within(todo).getByText("ждёт: Прокладка кабеля, Распаечные коробки")).toBeInTheDocument();
    expect(within(todo).getAllByText("нужно фото").length).toBeGreaterThan(0);
    await userEvent.click(within(review).getByRole("button", { name: /Распаечные коробки/ }));
    expect(onOpen).toHaveBeenCalledWith("boxes");
  });

  it("filters by domain and remembers the choice", async () => {
    const user = userEvent.setup();
    render(<WorkBoard state={workState()} run={live()} busy={false} open={null} onOpen={vi.fn()} />);
    await user.click(screen.getByRole("radio", { name: "Сантехника" }));
    expect(screen.queryByRole("button", { name: /Прокладка кабеля/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Водопровод/ })).toBeInTheDocument();
    expect(localStorage.getItem("work-domain")).toBe("plumbing");
  });

  it("adds a task after approval as extra work", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ "POST /api/projects/p1/work/tasks": workState() });
    render(<WorkBoard state={workState()} run={live()} busy={false} open={null} onOpen={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Добавить задачу" }));
    expect(screen.getByText(/задача пойдёт как доп. работа/)).toBeInTheDocument();
    const add = screen.getByRole("button", { name: "Добавить" });
    expect(add).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Название" }), "Ниша под роутер");
    await user.selectOptions(screen.getByRole("combobox", { name: "Раздел" }), "Другое");
    await user.selectOptions(screen.getByRole("combobox", { name: "Фото при сдаче" }), "обязательно");
    await user.click(add);
    expect(sent[0].body).toEqual({ title: "Ниша под роутер", description: "", domain: "other", photo: "required" });
    expect(screen.queryByRole("textbox", { name: "Название" })).toBeNull();
  });

  it("a draft is one column with its sum", () => {
    render(<WorkBoard state={draftState("draft")} run={live()} busy={false} open={null} onOpen={vi.fn()} />);
    expect(screen.getAllByRole("region")).toHaveLength(1);
    expect(screen.getByText(/Черновик из сметы/)).toBeInTheDocument();
    expect(screen.getAllByText(/^работа .+ · материалы /).length).toBeGreaterThan(1);
    expect(screen.getByRole("button", { name: "Отправить заказчику" })).toBeInTheDocument();
  });

  describe("drag and drop between the columns", () => {
    it("a plain transition is sent at once; the tile waits for the answer", async () => {
      const sent = stubApi({ "POST /api/projects/p1/work/tasks/water/status": workState() });
      render(<WorkBoard state={workState()} run={live()} busy={false} open={null} onOpen={vi.fn()} />);
      const water = tile("К работе", /Водопровод/);
      expect(water).toHaveAttribute("draggable", "true");
      drag(water, column("В работе"));
      expect(column("В работе")).toHaveAttribute("data-drop", "ok");
      expect(column("В работе")).toHaveAttribute("data-over");
      expect(column("На приёмке")).not.toHaveAttribute("data-drop");
      expect(water).toHaveClass(/dragging/);
      fireEvent.drop(column("В работе"));
      expect(water).toHaveAttribute("aria-busy", "true");
      expect(sent).toEqual([{ method: "POST", path: "/api/projects/p1/work/tasks/water/status", body: { to: "in_progress" } }]);
      await vi.waitFor(() => expect(water).not.toHaveAttribute("aria-busy"));
    });

    it("a transition with a comment or for the client opens the card with the intent", () => {
      const sent = stubApi({});
      const onOpen = vi.fn();
      render(<WorkBoard state={workState()} run={live()} busy={false} open={null} onOpen={onOpen} />);
      drag(tile("На приёмке", /Распаечные коробки/), column("Возвращено"));
      expect(column("Возвращено")).toHaveAttribute("data-drop", "card");
      expect(column("Принято")).toHaveAttribute("data-drop", "card");   // the studio accepts for the client
      fireEvent.drop(column("Возвращено"));
      expect(onOpen).toHaveBeenCalledWith("boxes", "returned");
      expect(sent).toHaveLength(0);
    });

    it("a blocked column is a warning target: the drop opens the card, nothing is sent", () => {
      const sent = stubApi({});
      const onOpen = vi.fn();
      render(<WorkBoard state={workState({ can: INSTALLER, assignees: [] })} run={live()} busy={false} open={null} onOpen={onOpen} />);
      const insulation = tile("К работе", /Замер изоляции/);   // waits for other tasks: the installer cannot start it
      drag(insulation, column("В работе"));
      expect(column("В работе")).toHaveAttribute("data-drop", "blocked");
      fireEvent.drop(column("В работе"));
      expect(onOpen).toHaveBeenCalledWith("insulation", "in_progress");
      expect(sent).toHaveLength(0);
    });

    it("a column no button leads to takes nothing; a tile without a transition is not draggable", () => {
      const sent = stubApi({});
      const onOpen = vi.fn();
      render(<WorkBoard state={workState({ can: INSTALLER, assignees: [] })} run={live()} busy={false} open={null} onOpen={onOpen} />);
      drag(tile("К работе", /Водопровод/), column("Принято"));
      expect(column("Принято")).not.toHaveAttribute("data-drop");
      fireEvent.drop(column("Принято"));
      expect(onOpen).not.toHaveBeenCalled();
      expect(sent).toHaveLength(0);
      expect(tile("На приёмке", /Распаечные коробки/)).toHaveAttribute("draggable", "false");   // the installer does not accept
      expect(tile("Принято", /Штробы/)).toHaveAttribute("draggable", "false");
    });

    it("a plan not approved yet has one column: nothing drags", () => {
      render(<WorkBoard state={draftState("draft")} run={live()} busy={false} open={null} onOpen={vi.fn()} />);
      for (const b of within(column("Предложено")).getAllByRole("button")) expect(b).toHaveAttribute("draggable", "false");
    });
  });

  it("warns when the model changed after the plan", () => {
    render(<WorkBoard state={workState({ model_version: 5 })} run={live()} busy={false} open={null} onOpen={vi.fn()} />);
    expect(screen.getByText(/Модель менялась после плана \(версия 3 → 5\)/)).toBeInTheDocument();
  });
});
