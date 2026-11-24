import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { stubApi } from "@/shared/testApi";
import { CLIENT, draftState, workState } from "@/widgets/WorkStage/mock";
import { WorkList } from "./index";

describe("WorkList", () => {
  it("lists the tasks in work order with status and what the client is asked", async () => {
    const onOpen = vi.fn();
    render(<WorkList state={workState({ can: CLIENT })} run={vi.fn()} busy={false} open={null} onOpen={onOpen} />);
    const items = within(screen.getByRole("list")).getAllByRole("button");
    expect(items[0]).toHaveTextContent(/^1Штробы/);
    expect(items[0]).toHaveTextContent("Принято");
    expect(items[0]).toHaveTextContent("оплачено");
    expect(items[0]).toHaveTextContent(/работа .+ · материалы /);
    const sums = screen.getByRole("banner").querySelector("dl")!;
    expect(sums).toHaveTextContent(/Работы.*Материалы.*Итого/);
    expect(sums).not.toHaveTextContent("имитация");
    expect(within(sums).getByRole("img", { name: "Цена условная: материалы пока не по рыночным ценам" }).parentElement).toHaveTextContent(/грн$/);
    expect(screen.getByRole("button", { name: /Распаечные коробки/ })).toHaveTextContent("Примите работу →");
    expect(screen.getByRole("button", { name: /Ниша под роутер/ })).toHaveTextContent("Согласуйте доп. работу →");
    expect(screen.getByText("Ждут вашего решения: 2")).toBeInTheDocument();
    await userEvent.click(items[1]);
    expect(onOpen).toHaveBeenCalledWith("cable");
  });

  it("a plan with the client asks to approve it", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ "POST /api/projects/p1/work/plan/approve": workState({ can: CLIENT }) });
    vi.stubGlobal("confirm", vi.fn(() => true));
    const run = vi.fn(async (call: (k: string) => Promise<unknown>) => { await call("p1"); return true; });
    render(<WorkList state={draftState("proposed", CLIENT)} run={run} busy={false} open={null} onOpen={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 2, name: "Утвердите план" })).toBeInTheDocument();
    expect(screen.queryByText("Принято")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Утвердить план" }));
    expect(confirm).toHaveBeenCalledWith(expect.stringMatching(/^Утвердить план работ на /));
    expect(sent[0].method).toBe("POST");
    expect(sent[0].body).toBeUndefined();
  });
});
