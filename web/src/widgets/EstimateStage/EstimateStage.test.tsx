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
      scope: { includes: ["разметка", "штробление"], result: "штроба под кабель" } },
    { cells: ["2", "Подрозетник", "шт", "—"] },
  ],
  total: ["", "Итого", "", "10 080"],
  notes: ["Цены — прайс студии"],
};
// builds before 2026-11-22 may still carry the removed `outside` list
const legacy = { ...electrical, outside: ["вывоз строительного мусора"] } as SideTable;

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

  it("PDF opens the estimate-for-print dialog, only where the estimate has a report", async () => {
    render(<EstimateStage items={[{ table: electrical, xlsx: null, report: "p1" },
                                  { table: { ...electrical, title: "Смета сантехники" }, xlsx: null }]} />);
    const pdf = screen.getAllByRole("button", { name: "Скачать PDF" });
    expect(pdf).toHaveLength(1);
    await userEvent.click(pdf[0]);
    expect(screen.getByRole("dialog", { name: "Смета для печати" })).toBeInTheDocument();
  });

  it("with a report, Excel opens the section choice instead of the file link", async () => {
    render(<EstimateStage items={[{ table: electrical, xlsx: "/api/projects/p1/out/estimate.xlsx", report: "p1" }]} />);
    expect(screen.queryByRole("link", { name: "Скачать Excel" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Скачать Excel" }));
    const dialog = screen.getByRole("dialog", { name: "Смета в Excel" });
    expect(dialog.querySelectorAll("input[type=checkbox]")).toHaveLength(4);
    expect(screen.queryByRole("checkbox", { name: "План электрики" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Открыть" })).toBeNull();
  });

  it("finish materials are a list without prices: quantities only, no section total, no mark", () => {
    const rows = [
      { cells: ["", "Чистовые материалы", "", "", "", ""], section: true },
      { cells: ["1", "Розетка", "шт", "4", "", ""] },
      { cells: ["", "Черновые работы", "", "", "", ""], section: true },
      { cells: ["1", "Штроба", "м", "10", "200", "2 000"] },
      { cells: ["", "Итого", "", "", "", "2 000"] },
    ];
    render(<EstimateStage items={[{ table: { ...electrical, rows }, xlsx: null }]} />);
    expect(screen.getByRole("row", { name: /Розетка/ })).toHaveTextContent(/Розеткашт4$/);
    const all = screen.getAllByRole("row");
    const socket = all.findIndex((r) => /Розетка/.test(r.textContent ?? ""));
    expect(all[socket + 1]).toHaveTextContent("Черновые работы");  // no total after the list
    expect(screen.queryByRole("img", { name: /Цена условная/ })).toBeNull();
  });

  it("does not show work outside the estimate, even if an old build has it", () => {
    render(<EstimateStage items={[{ table: legacy, xlsx: null }]} />);
    expect(screen.queryByRole("heading", { name: "Работы вне сметы" })).toBeNull();
    expect(screen.queryByText("вывоз строительного мусора")).toBeNull();
  });

  it("a work row unfolds what its price covers; the hint says what it is", async () => {
    const user = userEvent.setup();
    render(<EstimateStage items={[{ table: electrical, xlsx: null }]} />);
    expect(screen.getByText("Нажмите на работу, чтобы увидеть, что входит в её цену.")).toBeInTheDocument();
    const row = screen.getByRole("button", { name: "Штроба в кирпиче" });
    expect(row).toHaveAttribute("aria-expanded", "false");
    await user.click(row);
    expect(screen.getByRole("heading", { name: "Входит в цену" })).toBeInTheDocument();
    expect(screen.queryByText("Не входит")).not.toBeInTheDocument();
    expect(screen.getByText("штроба под кабель")).toBeInTheDocument();
    await user.click(row);
    expect(screen.queryByRole("heading", { name: "Входит в цену" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Что входит: Штроба в кирпиче" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("по трассам проекта");
  });
});
