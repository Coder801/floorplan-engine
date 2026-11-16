import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Button } from "./index";

describe("Button", () => {
  it("is a button that calls onClick and does not submit a form by itself", async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Сохранить</Button>);
    const button = screen.getByRole("button", { name: "Сохранить" });
    expect(button).toHaveAttribute("type", "button");
    await userEvent.click(button);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("does not react when disabled", async () => {
    const onClick = vi.fn();
    render(<Button disabled onClick={onClick}>Сохранить</Button>);
    const button = screen.getByRole("button", { name: "Сохранить" });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("is a toggle only with pressed", () => {
    const { rerender } = render(<Button>Слои</Button>);
    expect(screen.getByRole("button")).not.toHaveAttribute("aria-pressed");
    rerender(<Button pressed>Слои</Button>);
    expect(screen.getByRole("button", { pressed: true })).toHaveTextContent("Слои");
    rerender(<Button pressed={false}>Слои</Button>);
    expect(screen.getByRole("button", { pressed: false })).toBeInTheDocument();
  });

  it("with href is a link, the icon is hidden from screen readers", () => {
    render(<Button href="/out/project.dxf" download icon={<b>↓</b>}>Скачать</Button>);
    const link = screen.getByRole("link", { name: "Скачать" });
    expect(link).toHaveAttribute("href", "/out/project.dxf");
    expect(link).toHaveAttribute("download");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("keeps an explicit submit type", () => {
    render(<form><Button type="submit">Войти</Button></form>);
    expect(screen.getByRole("button", { name: "Войти" })).toHaveAttribute("type", "submit");
  });
});
