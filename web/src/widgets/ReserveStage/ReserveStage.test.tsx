import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { reserve } from "@/shared/testData";
import { ReserveStage } from "./index";

describe("ReserveStage", () => {
  it("saves a changed set; nothing to save until it changes, and not an empty one", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ReserveStage reserve={reserve()} editable busy={false} onSave={onSave} />);
    const save = screen.getByRole("button", { name: "Сохранить и пересчитать" });
    expect(save).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /QF1/ }));
    expect(screen.getByText("Отметьте хотя бы одну группу.")).toBeInTheDocument();
    expect(save).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /QF2/ }));
    await user.click(save);
    expect(onSave).toHaveBeenCalledWith(["QF2"]);
  });

  it("shows a refusal; read-only says why", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<ReserveStage reserve={reserve()} editable busy={false} onSave={vi.fn().mockRejectedValue(new Error("422: мало мощности"))} />);
    await user.click(screen.getByRole("checkbox", { name: /QF2/ }));
    await user.click(screen.getByRole("button", { name: "Сохранить и пересчитать" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не сохранено — 422: мало мощности");
    rerender(<ReserveStage reserve={reserve()} editable={false} busy={false} onSave={vi.fn()} />);
    expect(screen.getByText(/Здесь только просмотр/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Сохранить и пересчитать" })).toBeNull();
  });
});
