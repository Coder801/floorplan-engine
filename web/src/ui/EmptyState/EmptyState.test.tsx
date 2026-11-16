import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EmptyState } from "./index";

describe("EmptyState", () => {
  it("shows the text and the action under it", () => {
    render(<EmptyState action={<button>Загрузить</button>}>Листов нет</EmptyState>);
    expect(screen.getByText("Листов нет")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Загрузить" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
