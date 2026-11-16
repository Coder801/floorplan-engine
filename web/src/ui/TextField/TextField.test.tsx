import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TextField } from "./index";

describe("TextField", () => {
  it("is labelled, described by the hint and passes typing on", async () => {
    const onChange = vi.fn();
    render(<TextField label="Почта" hint="Пришлём ссылку" onChange={onChange} />);
    const field = screen.getByRole("textbox", { name: "Почта" });
    expect(field).toHaveAccessibleDescription("Пришлём ссылку");
    await userEvent.type(field, "a@b");
    expect(onChange).toHaveBeenCalledTimes(3);
  });

  it("an error replaces the hint and marks the field invalid", () => {
    render(<TextField label="Код" hint="6 цифр" error="Код не подошёл" id="code" />);
    const field = screen.getByRole("textbox", { name: "Код" });
    expect(field).toHaveAttribute("id", "code");
    expect(field).toBeInvalid();
    expect(field).toHaveAccessibleDescription("Код не подошёл");
    expect(screen.queryByText("6 цифр")).toBeNull();
  });

  it("without a label takes aria-label and can be disabled", () => {
    render(<TextField aria-label="Поиск" disabled />);
    expect(screen.getByRole("textbox", { name: "Поиск" })).toBeDisabled();
  });
});
