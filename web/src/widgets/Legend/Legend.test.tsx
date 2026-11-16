import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { item } from "@/shared/testData";
import { Legend } from "./index";

const entries = [
  { key: "socket", text: "Розетка", items: [item("E-SOCKET"), item("E-TEXT", { k: "f", d: "M0 0L5 5L0 5Z" })] },
  { key: "board", text: "Щит", items: [item("E-BOARD")] },
];

describe("Legend", () => {
  it("lists what the symbols mean and folds, remembering it", async () => {
    render(<Legend entries={entries} />);
    const head = screen.getByRole("button", { name: /Условные обозначения/ });
    expect(head).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Розетка")).toBeInTheDocument();
    await userEvent.click(head);
    expect(screen.queryByText("Розетка")).toBeNull();
    expect(localStorage.getItem("legend")).toBe("closed");
  });

  it("the title follows the project language; nothing without entries", () => {
    const { container, rerender } = render(<Legend entries={entries} language="en" />);
    expect(screen.getByRole("group", { name: "Legend" })).toBeInTheDocument();
    rerender(<Legend entries={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
