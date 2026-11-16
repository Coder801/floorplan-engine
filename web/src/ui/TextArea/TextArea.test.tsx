import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TextArea } from "./index";

describe("TextArea", () => {
  it("is labelled, described by the hint and passes typing on", async () => {
    const onChange = vi.fn();
    render(<TextArea label="Что не так" hint="Опишите шаги" counter="0 / 2000" onChange={onChange} />);
    const area = screen.getByRole("textbox", { name: "Что не так" });
    expect(area).toHaveAccessibleDescription("Опишите шаги");
    expect(area).not.toBeInvalid();
    expect(screen.getByText("0 / 2000")).toBeInTheDocument();
    await userEvent.type(area, "ок");
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it("an error replaces the hint and marks the field invalid", () => {
    render(<TextArea label="Текст" hint="Подсказка" error="Слишком длинно" />);
    const area = screen.getByRole("textbox", { name: "Текст" });
    expect(area).toBeInvalid();
    expect(area).toHaveAccessibleDescription("Слишком длинно");
    expect(screen.getByRole("alert")).toHaveTextContent("Слишком длинно");
    expect(screen.queryByText("Подсказка")).toBeNull();
  });
});
