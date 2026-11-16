import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { stubApi } from "@/shared/testApi";
import type { WorkRun } from "@/shared/work";
import { draftState, TASKS, workState } from "@/widgets/WorkStage/mock";
import { WorkMerge } from "./index";

const live = (): WorkRun => vi.fn(async (call) => { await call("p1"); return true; });
const ask = vi.fn(() => true);
beforeEach(() => { ask.mockReset().mockReturnValue(true); vi.stubGlobal("confirm", ask); });

describe("WorkMerge", () => {
  it("merges into the picked task after a question and opens it", async () => {
    const user = userEvent.setup();
    const state = draftState("draft");
    const from = state.tasks.find((t) => t.id === "boxes")!;
    const sent = stubApi({ "POST /api/projects/p1/work/tasks/boxes/merge": state });
    const onMerged = vi.fn();
    render(<WorkMerge task={from} state={state} run={live()} busy={false} onMerged={onMerged} />);
    await user.click(screen.getByRole("button", { name: "Объединить с…" }));
    await user.click(screen.getByRole("button", { name: "Куда влить" }));
    await user.click(screen.getByRole("option", { name: /Установка корпуса щита/ }));
    ask.mockReturnValueOnce(false);
    await user.click(screen.getByRole("button", { name: "Объединить" }));
    expect(sent).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Объединить" }));
    expect(ask).toHaveBeenLastCalledWith(expect.stringContaining("Влить «Распаечные коробки» в «Установка корпуса щита»?"));
    expect(sent[0].body).toEqual({ into: "board" });
    expect(onMerged).toHaveBeenCalledWith("board");
  });

  it("a task with photos or payments is not merged and says why", () => {
    render(<WorkMerge task={{ ...TASKS[0], money_editable: true }} state={workState()} run={live()} busy={false} onMerged={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Объединить с…" })).toHaveAccessibleDescription("У задачи есть фото — объединить нельзя.");
  });

  it("cancel folds the form", async () => {
    const user = userEvent.setup();
    const state = draftState("draft");
    render(<WorkMerge task={state.tasks[2]} state={state} run={live()} busy={false} onMerged={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Объединить с…" }));
    await user.click(screen.getByRole("button", { name: "Отмена" }));
    expect(screen.getByRole("button", { name: "Объединить с…" })).toBeEnabled();
  });
});
