import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Boundary } from "./index";

function Broken(): never {
  throw new Error("нет слоя");
}

afterEach(() => vi.restoreAllMocks());

describe("Boundary", () => {
  it("shows the children while they render", () => {
    render(<Boundary><p>Лист</p></Boundary>);
    expect(screen.getByText("Лист")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows the error and a reload button instead of a broken sheet", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(<Boundary><Broken /></Boundary>);
    expect(screen.getByRole("alert")).toHaveTextContent("Лист не отрисовался: нет слоя");
    expect(screen.getByRole("button", { name: "Обновить страницу" })).toBeInTheDocument();
  });
});
