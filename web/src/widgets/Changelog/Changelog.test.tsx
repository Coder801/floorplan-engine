import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { APP_VERSION } from "@/shared/version";
import { Changelog } from "./index";

describe("Changelog", () => {
  it("lists releases newest first with their kinds of changes, the current one marked", async () => {
    const onClose = vi.fn();
    render(<Changelog onClose={onClose} releases={[
      { version: APP_VERSION, date: "2026-11-15", changes: { added: ["Мастер настройки"], fixed: ["Подписи"] } },
      { version: "0.1.0", date: null, changes: { changed: ["Формат"] } },
    ]} />);
    const current = screen.getByRole("heading", { level: 3, name: `Версия ${APP_VERSION}` }).closest("section")!;
    expect(within(current).getByText("у вас")).toBeInTheDocument();
    expect(within(current).getByRole("heading", { name: "Новое" })).toBeInTheDocument();
    expect(within(current).getByText("Мастер настройки")).toBeInTheDocument();
    expect(within(current).queryByRole("heading", { name: "Изменилось" })).toBeNull();
    const old = screen.getByRole("heading", { level: 3, name: "Версия 0.1.0" }).closest("section")!;
    expect(within(old).queryByText("у вас")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("says when there is nothing yet", () => {
    render(<Changelog onClose={vi.fn()} releases={[]} />);
    expect(screen.getByText("Список изменений пока пуст.")).toBeInTheDocument();
  });
});
