import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { stubApi } from "@/shared/testApi";
import type { WorkRun } from "@/shared/work";
import { draftState, workState } from "@/widgets/WorkStage/mock";
import { WorkPlanActions } from "./index";

const live = (): WorkRun => vi.fn(async (call) => { await call("p1"); return true; });
const ask = vi.fn();
beforeEach(() => { ask.mockReset(); vi.stubGlobal("confirm", ask); });

describe("WorkPlanActions", () => {
  it("a draft is sent to the client or discarded after a question", async () => {
    const user = userEvent.setup();
    const sent = stubApi({
      "POST /api/projects/p1/work/plan/propose": draftState("proposed"),
      "POST /api/projects/p1/work/plan/discard": workState({ plan: null }),
    });
    render(<WorkPlanActions state={draftState("draft")} run={live()} busy={false} />);
    await user.click(screen.getByRole("button", { name: "Отправить заказчику" }));
    expect(sent.at(-1)?.path).toBe("/api/projects/p1/work/plan/propose");
    ask.mockReturnValueOnce(false);
    await user.click(screen.getByRole("button", { name: "Сбросить черновик" }));
    expect(sent).toHaveLength(1);
    ask.mockReturnValueOnce(true);
    await user.click(screen.getByRole("button", { name: "Сбросить черновик" }));
    expect(sent.at(-1)?.path).toBe("/api/projects/p1/work/plan/discard");
  });

  it("the studio approves for the client only with how the client confirmed", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ "POST /api/projects/p1/work/plan/approve": workState() });
    render(<WorkPlanActions state={draftState("proposed")} run={live()} busy={false} />);
    expect(screen.getByRole("button", { name: "Отозвать план" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Утвердить план" }));
    expect(ask).not.toHaveBeenCalled();
    const ok = screen.getByRole("button", { name: "Подтвердить за заказчика" });
    expect(ok).toBeDisabled();
    await user.click(screen.getByRole("radio", { name: "В Telegram" }));
    await user.type(screen.getByRole("textbox", { name: "Примечание" }), " скрин в чате ");
    await user.click(ok);
    expect(sent[0].body).toEqual({ on_behalf: "telegram", note: "скрин в чате" });
    await vi.waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("only the add button with a form to open; buttons are off while busy", () => {
    const onAdd = vi.fn();
    const { rerender } = render(<WorkPlanActions state={workState()} run={live()} busy={false} />);
    expect(screen.queryByRole("button")).toBeNull();
    rerender(<WorkPlanActions state={workState()} run={live()} busy onAdd={onAdd} />);
    expect(screen.getByRole("button", { name: "Добавить задачу" })).toBeDisabled();
  });
});
