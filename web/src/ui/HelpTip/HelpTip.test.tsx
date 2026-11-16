import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { HelpTip } from "./index";

describe("HelpTip", () => {
  it("opens from the keyboard and describes the button; Esc closes it", async () => {
    const user = userEvent.setup();
    render(<HelpTip label="Что такое резерв" text="Свободные места в щите" />);
    const button = screen.getByRole("button", { name: "Что такое резерв" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("tooltip")).toBeNull();
    await user.tab();
    await user.keyboard("{Enter}");
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(button).toHaveAccessibleDescription("Свободные места в щите");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
  });

  it("opens while the mouse is over it", async () => {
    const user = userEvent.setup();
    render(<HelpTip label="Подсказка" text="Текст" mark="i" />);
    expect(screen.getByRole("button")).toHaveTextContent("i");
    await user.hover(screen.getByRole("button"));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Текст");
    await user.unhover(screen.getByRole("button"));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("closes on a click outside", async () => {
    const user = userEvent.setup();
    render(<><HelpTip label="Подсказка" text="Текст" /><p>мимо</p></>);
    await user.click(screen.getByRole("button"));
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    await user.click(screen.getByText("мимо"));
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
  });
});
