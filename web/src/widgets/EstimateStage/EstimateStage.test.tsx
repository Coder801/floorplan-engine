import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { SideTable } from "@/shared/types";
import { EstimateStage } from "./index";

const electrical: SideTable = {
  title: "Смета электрики", columns: ["№", "Позиция", "Ед.", "Сумма"], align: ["left", "left", "center", "right"],
  rows: [
    { cells: ["", "Работы", "", ""], section: true },
    { cells: ["1", "Штроба в кирпиче", "м", "10 080"], hint: "по трассам проекта",
      scope: { includes: ["разметка", "штробление"], excludes: ["вывоз мусора — отдельная позиция"], result: "штроба под кабель" } },
    { cells: ["2", "Подрозетник", "шт", "—"] },
  ],
  total: ["", "Итого", "", "10 080"],
  notes: ["Цены — прайс студии"],
};

describe("EstimateStage", () => {
  it("shows each estimate with its Excel file, total and notes", () => {
    render(<EstimateStage items={[{ table: electrical, xlsx: "/api/projects/p1/out/estimate.xlsx" },
                                  { table: { ...electrical, title: "Смета сантехники", rows: [] }, xlsx: null }]} />);
    expect(screen.getByRole("heading", { level: 1, name: "Смета электрики" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Смета сантехники" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Скачать Excel" })).toHaveLength(1);
    expect(screen.getAllByRole("row", { name: /Итого/ })[0]).toHaveTextContent("10 080");
    expect(screen.getAllByText("Цены — прайс студии")).toHaveLength(2);
  });

  it("a work row unfolds what its price covers; the hint says what it is", async () => {
    const user = userEvent.setup();
    render(<EstimateStage items={[{ table: electrical, xlsx: null }]} />);
    expect(screen.getByText("Нажмите на работу, чтобы увидеть, что входит в её цену.")).toBeInTheDocument();
    const row = screen.getByRole("button", { name: "Штроба в кирпиче" });
    expect(row).toHaveAttribute("aria-expanded", "false");
    await user.click(row);
    expect(screen.getByRole("heading", { name: "Входит в цену" })).toBeInTheDocument();
    expect(screen.getByText("вывоз мусора — отдельная позиция")).toBeInTheDocument();
    expect(screen.getByText("штроба под кабель")).toBeInTheDocument();
    await user.click(row);
    expect(screen.queryByRole("heading", { name: "Входит в цену" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Что входит: Штроба в кирпиче" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("по трассам проекта");
  });
});
