import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ErrorState } from "./index";

describe("ErrorState", () => {
  it("announces the error and shows the action", () => {
    render(<ErrorState action={<button>Повторить</button>}>Сервер не ответил</ErrorState>);
    expect(screen.getByRole("alert")).toHaveTextContent("Сервер не ответил");
    expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument();
  });
});
