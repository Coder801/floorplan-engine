import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { WorkConfirm } from "./index";

describe("WorkConfirm", () => {
  it("asks the channel first, the note is optional", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<WorkConfirm action="Принять" detail="1 000 грн" busy={false} onConfirm={onConfirm} onCancel={vi.fn()} />);
    expect(screen.getByRole("dialog", { name: "Как заказчик подтвердил?" })).toHaveAccessibleDescription(/«Принять».*1 000 грн/);
    expect(screen.getByRole("radio", { name: "По звонку" })).toHaveFocus();
    const ok = screen.getByRole("button", { name: "Подтвердить за заказчика" });
    expect(ok).toBeDisabled();
    await user.click(screen.getByRole("radio", { name: "По звонку" }));
    await user.click(ok);
    expect(onConfirm).toHaveBeenCalledWith({ channel: "phone", note: "" });
  });

  it("Отмена and Esc cancel", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(<WorkConfirm action="Принять" busy={false} onConfirm={vi.fn()} onCancel={onCancel} />);
    await user.click(screen.getByRole("button", { name: "Отмена" }));
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(2);
  });
});
