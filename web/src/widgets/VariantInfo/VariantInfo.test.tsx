import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { variants, variantSummary } from "@/shared/testData";
import { VariantInfo } from "./index";

describe("VariantInfo", () => {
  it("lists what the project holds and opens the wizard", async () => {
    const onEdit = vi.fn();
    render(<VariantInfo variants={variants({ led: true, conduit: null })} canChoose onEdit={onEdit} />);
    expect(screen.getByText("Трасса кабеля").nextSibling).toHaveTextContent("По потолку");
    expect(screen.getByText("Соединение розеток").nextSibling).toHaveTextContent("Через коробки");
    expect(screen.getByText(/· типовое/)).toBeInTheDocument();
    expect(screen.getByText("18 апп. · 320 м кабеля · 60 м штроб")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Изменить" }));
    expect(onEdit).toHaveBeenCalledOnce();
  });

  it("read-only without the right to choose; marks route edits", () => {
    render(<VariantInfo variants={variants({ items: [variantSummary({ edited: true })] })} canChoose={false} />);
    expect(screen.getByText("Вариант выбирает студия: здесь — только просмотр.")).toBeInTheDocument();
    expect(screen.getByText(/есть ваши правки трасс/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
