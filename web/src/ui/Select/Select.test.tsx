import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Select } from "./index";

const OPTIONS = [
  { value: "uk", label: "Українська" },
  { value: "ru", label: "Русский" },
  { value: "en", label: "English" },
];

describe("Select", () => {
  it("shows the chosen option and opens a list with it selected and focused", async () => {
    const user = userEvent.setup();
    render(<Select label="Язык" options={OPTIONS} value="ru" onChange={() => {}} />);
    const button = screen.getByRole("button", { name: "Язык" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("listbox")).toBeNull();
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("listbox", { name: "Язык" })).toBeInTheDocument();
    const current = screen.getByRole("option", { selected: true });
    expect(current).toHaveTextContent("Русский");
    expect(current).toHaveFocus();
  });

  it("arrows move over the options (wrapping), a pick passes the value, closes and returns the focus", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Select label="Язык" options={OPTIONS} value="ru" onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Язык" }));
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("option", { name: /English/ })).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("option", { name: /Українська/ })).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("option", { name: /English/ })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledWith("en");
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
    expect(screen.getByRole("button", { name: "Язык" })).toHaveFocus();
  });

  it("Esc closes the list without a choice", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Select label="Язык" options={OPTIONS} value="ru" onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Язык" }));
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
    expect(onChange).not.toHaveBeenCalled();
  });
});
