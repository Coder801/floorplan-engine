import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Modal } from "./index";

describe("Modal", () => {
  it("is a modal dialog over the page that takes the focus and gives it back", () => {
    const { rerender } = render(<button>Открыть</button>);
    screen.getByRole("button", { name: "Открыть" }).focus();
    rerender(<><button>Открыть</button><Modal label="Отзыв" onClose={() => {}}><p>Текст</p></Modal></>);
    const dialog = screen.getByRole("dialog", { name: "Отзыв" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveFocus();
    rerender(<button>Открыть</button>);
    expect(screen.getByRole("button", { name: "Открыть" })).toHaveFocus();
  });

  it("closes on Esc and on a click on the veil, not on a click inside", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Modal label="Отзыв" onClose={onClose}><p>Текст</p></Modal>);
    await user.click(screen.getByText("Текст"));
    expect(onClose).not.toHaveBeenCalled();
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("dialog").parentElement!);
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("closeOnVeil false keeps a half-filled form open on a miss", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Modal label="Форма" onClose={onClose} closeOnVeil={false}><input aria-label="Имя" /></Modal>);
    await user.click(screen.getByRole("dialog").parentElement!);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("keeps Tab inside the card", async () => {
    const user = userEvent.setup();
    render(
      <>
        <button>Снаружи</button>
        <Modal label="Вход" onClose={() => {}}><button>Первая</button><button>Последняя</button></Modal>
      </>,
    );
    await user.tab();
    expect(screen.getByRole("button", { name: "Первая" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Последняя" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Первая" })).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Последняя" })).toHaveFocus();
  });

  it("as a form submits; busy is announced", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn((e: { preventDefault: () => void }) => e.preventDefault());
    render(<Modal as="form" label="Код" busy onSubmit={onSubmit}><button type="submit">Войти</button></Modal>);
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-busy", "true");
    await user.click(screen.getByRole("button", { name: "Войти" }));
    expect(onSubmit).toHaveBeenCalledOnce();
  });
});
