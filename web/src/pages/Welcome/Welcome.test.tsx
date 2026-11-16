import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { summary } from "@/shared/testData";
import { Welcome } from "./index";

describe("Welcome", () => {
  it("lists the projects as cards and opens the clicked one", async () => {
    const onOpen = vi.fn();
    render(<Welcome list={[summary(), summary({ id: "p2", name: "dacha", title: "Дача" })]} onOpen={onOpen}
                    settings={<button>Настройки</button>} />);
    expect(screen.getByRole("dialog", { name: /Shtroba/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Настройки" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Дача/ }));
    expect(onOpen).toHaveBeenCalledWith("p2");
  });

  it("without projects says how to build one", () => {
    render(<Welcome list={[]} onOpen={vi.fn()} />);
    expect(screen.getByText("Нет проектов в projects/ — соберите хотя бы один:")).toBeInTheDocument();
    expect(screen.getByText("uv run floorplan-engine build projects/<имя>")).toBeInTheDocument();
  });
});
