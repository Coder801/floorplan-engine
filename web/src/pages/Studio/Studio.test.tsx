import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { stubApi } from "@/shared/testApi";
import { pricePage } from "@/shared/testData";
import type { Account } from "@/widgets/Settings";
import { Studio } from "./index";

const firm: Account = {
  name: "Иван", plan: "pro", space: "Искра", visitor: false, logout: vi.fn(),
  firm: { kind: "studio", name: "Искра", business: "electric", city: "Киев" },
};

describe("Studio", () => {
  it("shows the firm profile read-only and switches sections", async () => {
    const user = userEvent.setup();
    const onSection = vi.fn();
    render(<Studio account={firm} section="profile" onSection={onSection} onBack={vi.fn()} />);
    expect(screen.getByRole("dialog", { name: "Настройки студии" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Название" })).toHaveValue("Искра");
    expect(screen.getByRole("textbox", { name: "Чем занимается" })).toHaveValue("Электромонтаж");
    expect(screen.getByRole("textbox", { name: "Город" })).toBeDisabled();
    expect(screen.getByLabelText("Логотип")).toHaveTextContent("И");
    expect(screen.getByRole("button", { name: "Студия" })).toHaveAttribute("aria-current", "page");
    await user.click(screen.getByRole("button", { name: "Прайс · электрика" }));
    expect(onSection).toHaveBeenCalledWith("prices");
  });

  it("says why there is no profile", () => {
    const { rerender } = render(<Studio account={null} section="profile" onSection={vi.fn()} onBack={vi.fn()} />);
    expect(screen.getByText("Вход выключен — профиль студии хранится в учётке фирмы.")).toBeInTheDocument();
    rerender(<Studio account={{ ...firm, firm: null }} section="profile" onSection={vi.fn()} onBack={vi.fn()} />);
    expect(screen.getByText("Профиль фирмы не заполнен: учётка без фирмы.")).toBeInTheDocument();
  });

  it("asks before leaving unsaved prices", async () => {
    const user = userEvent.setup();
    stubApi({ "GET /api/prices": pricePage() });
    const ask = vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true);
    vi.stubGlobal("confirm", ask);
    const onBack = vi.fn();
    render(<Studio account={firm} section="prices" onSection={vi.fn()} onBack={onBack} />);
    await user.type(await screen.findByRole("textbox", { name: /Цена:/ }), "5");
    await user.keyboard("{Escape}");
    expect(ask).toHaveBeenCalledWith("Есть несохранённые цены. Уйти без сохранения?");
    expect(onBack).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Назад" }));
    expect(onBack).toHaveBeenCalledOnce();
  });

  it("leaves at once without edits", async () => {
    const onBack = vi.fn();
    render(<Studio account={firm} section="profile" onSection={vi.fn()} onBack={onBack} />);
    await userEvent.keyboard("{Escape}");
    expect(onBack).toHaveBeenCalledOnce();
  });
});
