import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { fail, stubApi } from "@/shared/testApi";
import type { WorkState } from "@/shared/types";
import { CLIENT, INSTALLER, noRun, workState } from "./mock";
import { useWork } from "./useWork";
import { WorkStage } from "./index";

const stage = (over: Partial<Parameters<typeof WorkStage>[0]> = {}) =>
  render(<WorkStage state={null} error={null} busy={false} run={noRun} open={null} onOpen={vi.fn()} {...over} />);

describe("WorkStage", () => {
  it("loads, then fails in words", () => {
    const { rerender } = stage();
    expect(screen.getByRole("status")).toHaveTextContent("Загрузка задач…");
    rerender(<WorkStage state={null} error="403: нет доступа" busy={false} run={noRun} open={null} onOpen={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("403: нет доступа");
  });

  it("no plan: the studio creates it from the estimate, others wait", async () => {
    const run = vi.fn().mockResolvedValue(true);
    const { unmount } = stage({ state: workState({ plan: null, tasks: [] }), run });
    expect(screen.getByText(/Плана работ ещё нет/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Создать задачи из сметы" }));
    expect(run).toHaveBeenCalledOnce();
    unmount();
    const second = stage({ state: workState({ plan: null, tasks: [], draft_available: false }) });
    expect(screen.getByText(/нет сметы для задач/)).toBeInTheDocument();
    second.unmount();
    stage({ state: workState({ plan: null, tasks: [], can: CLIENT }) });
    expect(screen.getByText("Студия ещё готовит план работ")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("the studio and installers get the board, the client the list; a refusal shows over it", () => {
    const { unmount } = stage({ state: workState({ can: INSTALLER }), error: "409: занято" });
    expect(screen.getByRole("region", { name: "В работе" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("409: занято");
    unmount();
    stage({ state: workState({ can: CLIENT }), error: "409: занято", open: "cable" });
    expect(screen.queryByRole("region", { name: "В работе" })).toBeNull();
    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();  // the open card says it
  });
});

describe("useWork", () => {
  it("loads the state when the tab opens and replaces it with the answer of a write", async () => {
    const sent = stubApi({ "GET /api/projects/p1/work": workState(), "POST /api/projects/p1/work/plan": workState({ tasks: [] }) });
    const { result, rerender } = renderHook(({ active }) => useWork("p1", active), { initialProps: { active: false } });
    expect(sent).toHaveLength(0);
    rerender({ active: true });
    await vi.waitFor(() => expect(result.current.state?.tasks.length).toBeGreaterThan(0));
    let ok = false;
    await act(async () => { ok = await result.current.run((key) => import("@/shared/api").then((api) => api.createWorkPlan(key))); });
    expect(ok).toBe(true);
    expect(result.current.state?.tasks).toEqual([]);
    expect(result.current.busy).toBe(false);
  });

  it("keeps the server's refusal until cleared; another project starts empty", async () => {
    stubApi({ "GET /api/projects/p1/work": workState(), "GET /api/projects/p2/work": fail(404, "нет плана") });
    const { result, rerender } = renderHook(({ key }) => useWork(key, true), { initialProps: { key: "p1" as string | null } });
    await vi.waitFor(() => expect(result.current.state).not.toBeNull());
    let ok = true;
    await act(async () => { ok = await result.current.run(() => Promise.reject(new Error("409: план закрыт"))); });
    expect(ok).toBe(false);
    expect(result.current.error).toBe("409: план закрыт");
    act(() => result.current.clearError());
    expect(result.current.error).toBeNull();
    rerender({ key: "p2" });
    expect(result.current.state).toBeNull();
    await vi.waitFor(() => expect(result.current.error).toBe("нет плана"));
    rerender({ key: null });
    let none = true;
    await act(async () => { none = await result.current.run(() => Promise.resolve({} as WorkState)); });
    expect(none).toBe(false);
  });
});
