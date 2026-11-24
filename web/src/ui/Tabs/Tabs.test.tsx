import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Tabs, type Tab } from "./index";

const TABS: Tab<"work" | "lines" | "feed">[] = [
  { value: "work", label: "Работа", mark: true, ariaLabel: "Работа — требует внимания" },
  { value: "lines", label: "Позиции", count: "1 500 грн" },
  { value: "feed", label: "Лента", count: 2 },
];

describe("Tabs", () => {
  it("is a tab list; only the chosen panel is shown, with its count and mark", () => {
    render(<Tabs label="Разделы" tabs={TABS} value="lines" onChange={() => {}}><p>строки</p></Tabs>);
    expect(screen.getByRole("tablist", { name: "Разделы" })).toBeInTheDocument();
    const lines = screen.getByRole("tab", { name: /Позиции/ });
    expect(lines).toHaveAttribute("aria-selected", "true");
    expect(lines).toHaveTextContent("1 500 грн");
    expect(screen.getByRole("tab", { name: "Работа — требует внимания" })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tabpanel", { name: /Позиции/ })).toHaveTextContent("строки");
  });

  it("a click and the arrows choose a tab", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Tabs label="Разделы" tabs={TABS} value="work" onChange={onChange} />);
    await user.click(screen.getByRole("tab", { name: /Лента/ }));
    expect(onChange).toHaveBeenLastCalledWith("feed");
    screen.getByRole("tab", { name: "Работа — требует внимания" }).focus();
    await user.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenLastCalledWith("lines");
    await user.keyboard("{ArrowLeft}");
    expect(onChange).toHaveBeenLastCalledWith("feed");   // wraps around from the first
    await user.keyboard("{End}");
    expect(onChange).toHaveBeenLastCalledWith("feed");
    await user.keyboard("{Home}");
    expect(onChange).toHaveBeenLastCalledWith("work");
  });
});
