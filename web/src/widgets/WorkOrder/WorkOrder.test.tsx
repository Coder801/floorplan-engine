import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { stubApi } from "@/shared/testApi";
import type { WorkRun } from "@/shared/work";
import { TASKS, workState } from "@/widgets/WorkStage/mock";
import { WorkOrder } from "./index";

const live = (): WorkRun => vi.fn(async (call) => { await call("p1"); return true; });
const cable = TASKS.find((t) => t.id === "cable")!;

describe("WorkOrder", () => {
  it("moves the task up and down by its neighbours' places", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ "PATCH /api/projects/p1/work/tasks/cable": workState() });
    render(<WorkOrder task={cable} state={workState()} run={live()} busy={false} editable />);
    expect(screen.getByText("2 из 7")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Выше" }));
    expect(sent.at(-1)?.body).toEqual({ position: 0 });
    await user.click(screen.getByRole("button", { name: "Ниже" }));
    expect(sent.at(-1)?.body).toEqual({ position: 2 });
  });

  it("the first one has no way up", () => {
    render(<WorkOrder task={TASKS[0]} state={workState()} run={live()} busy={false} editable />);
    expect(screen.getByRole("button", { name: "Выше" })).toBeDisabled();
    expect(screen.getByText("ни после каких")).toBeInTheDocument();
  });

  it("edits the tasks it goes after", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ "PATCH /api/projects/p1/work/tasks/cable": workState() });
    render(<WorkOrder task={cable} state={workState()} run={live()} busy={false} editable />);
    expect(screen.getByText(/1\. Штробы, проходы, подрозетники/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Изменить" }));
    expect(screen.getByRole("checkbox", { name: "1. Штробы, проходы, подрозетники" })).toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "3. Распаечные коробки" }));
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(sent[0].body).toEqual({ after: ["chases", "boxes"] });
  });

  it("read-only shows only what it goes after, or nothing", () => {
    const { container, rerender } = render(<WorkOrder task={cable} state={workState()} run={live()} busy={false} editable={false} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/Штробы/)).toBeInTheDocument();
    rerender(<WorkOrder task={TASKS[0]} state={workState()} run={live()} busy={false} editable={false} />);
    expect(container).toBeEmptyDOMElement();
  });
});
