import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import i18n, { setLanguage } from "@/shared/i18n";
import type { Account } from "./index";
import { Settings } from "./index";

afterEach(() => setLanguage("ru"));

const account = (over: Partial<Account> = {}): Account =>
  ({ name: "Иван", plan: "pro", space: "Ампер", visitor: false, logout: vi.fn(), ...over });

function open(over: Partial<Parameters<typeof Settings>[0]> = {}) {
  const props = { account: account(), theme: "system" as const, onTheme: vi.fn(), mode: "simple" as const, onMode: vi.fn(), ...over };
  render(<Settings {...props} />);
  return props;
}

describe("Settings", () => {
  it("the gear opens the panel with the account and the plan; log out works", async () => {
    const user = userEvent.setup();
    const props = open();
    const gear = screen.getByRole("button", { name: "Настройки" });
    expect(gear).toHaveAttribute("aria-expanded", "false");
    await user.click(gear);
    const panel = screen.getByRole("dialog", { name: "Настройки" });
    expect(within(panel).getByText("Иван")).toBeInTheDocument();
    expect(within(panel).getByText("Ампер")).toBeInTheDocument();
    expect(within(panel).getByText("проекты без ограничений, приглашения")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Выйти" }));
    expect(props.account!.logout).toHaveBeenCalledOnce();
  });

  it("without login there is no account and no plan", async () => {
    open({ account: null });
    await userEvent.click(screen.getByRole("button", { name: "Настройки" }));
    expect(screen.getByText("Вход выключен — локальный просмотр")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "План" })).toBeNull();
  });

  it("names the plan of a guest and of a code", async () => {
    const user = userEvent.setup();
    open({ account: account({ space: null, plan: null, code: true }) });
    await user.click(screen.getByRole("button", { name: "Настройки" }));
    expect(screen.getByText("По коду")).toBeInTheDocument();
  });

  it("switches the mode and the theme", async () => {
    const user = userEvent.setup();
    const props = open();
    await user.click(screen.getByRole("button", { name: "Настройки" }));
    expect(screen.getByRole("radio", { name: "Простой" })).toBeChecked();
    await user.click(screen.getByRole("radio", { name: "Инженерный" }));
    expect(props.onMode).toHaveBeenCalledWith("engineering");
    await user.click(screen.getByRole("radio", { name: "Тёмная" }));
    expect(props.onTheme).toHaveBeenCalledWith("dark");
  });

  it("studio, feedback and what's new close the panel and open their screen; none without a handler", async () => {
    const user = userEvent.setup();
    const onStudio = vi.fn(), onFeedback = vi.fn(), onChanges = vi.fn();
    open({ onStudio, onFeedback, onChanges });
    const gear = screen.getByRole("button", { name: "Настройки" });
    await user.click(gear);
    await user.click(screen.getByRole("button", { name: /Настройки студии/ }));
    expect(onStudio).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await user.click(gear);
    await user.click(screen.getByRole("button", { name: /Оставить отзыв/ }));
    expect(onFeedback).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await user.click(gear);
    await user.click(screen.getByRole("button", { name: "Что нового" }));
    expect(onChanges).toHaveBeenCalledOnce();
  });

  it("has no studio, feedback or changes buttons without their handlers", async () => {
    open();
    await userEvent.click(screen.getByRole("button", { name: "Настройки" }));
    expect(screen.queryByRole("button", { name: /Настройки студии/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Оставить отзыв/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Что нового" })).toBeNull();
  });

  it("switches the interface language at once and remembers it", async () => {
    const user = userEvent.setup();
    open();
    await user.click(screen.getByRole("button", { name: "Настройки" }));
    await user.click(screen.getByRole("button", { name: /Русский/ }));
    const list = screen.getByRole("listbox", { name: "Язык" });
    expect(within(list).getByRole("option", { name: /Русский/ })).toHaveAttribute("aria-selected", "true");
    await user.click(within(list).getByRole("option", { name: /English/ }));
    expect(i18n.language).toBe("en");
    expect(localStorage.getItem("lang")).toBe("en");
    expect(await screen.findByRole("heading", { name: "Theme" })).toBeInTheDocument();
  });

  it("Esc closes the panel", async () => {
    const user = userEvent.setup();
    open();
    await user.click(screen.getByRole("button", { name: "Настройки" }));
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
