import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { summary } from "@/shared/testData";
import { ProjectsMenu } from "./index";

function open(over: Partial<Parameters<typeof ProjectsMenu>[0]> = {}) {
  const props = { list: [summary(), summary({ id: "p2", name: "dacha", title: "Дача" })], current: "kv42", closing: false,
    onOpen: vi.fn(), onClose: vi.fn(), onClosed: vi.fn(), ...over };
  return { ...props, ...render(<ProjectsMenu {...props} />) };
}

describe("ProjectsMenu", () => {
  it("marks the current project (by key or old name) and opens another", async () => {
    const { onOpen } = open();
    const nav = screen.getByRole("navigation", { name: "Проекты" });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Квартира 42/ })).toHaveAttribute("aria-current", "true");
    await userEvent.click(screen.getByRole("button", { name: /Дача/ }));
    expect(onOpen).toHaveBeenCalledWith("p2");
  });

  it("closes by the button and by Esc; slid out, it asks to be removed", async () => {
    const { onClose, onClosed, rerender, ...props } = open();
    await userEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(2);
    rerender(<ProjectsMenu {...props} onClose={onClose} onClosed={onClosed} closing />);
    // jsdom has no AnimationEvent but has WebkitAnimation styles: React listens to the prefixed event
    fireEvent(screen.getByRole("navigation"), new Event("webkitAnimationEnd", { bubbles: true }));
    expect(onClosed).toHaveBeenCalledOnce();
  });

  it("says when there is nothing to open", () => {
    open({ list: [] });
    expect(screen.getByText("Нет собранных проектов.")).toBeInTheDocument();
  });
});
