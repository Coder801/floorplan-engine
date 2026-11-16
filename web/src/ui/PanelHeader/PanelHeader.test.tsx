import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PanelHeader } from "./index";

describe("PanelHeader", () => {
  it("shows the title as a heading with its buttons", () => {
    render(<PanelHeader title="Слои" id="layers" start={<button>Назад</button>}><button>Закрыть</button></PanelHeader>);
    expect(screen.getByRole("heading", { level: 2, name: "Слои" })).toHaveAttribute("id", "layers");
    expect(screen.getByRole("button", { name: "Назад" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Закрыть" })).toBeInTheDocument();
  });
});
