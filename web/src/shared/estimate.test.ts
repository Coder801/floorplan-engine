import { describe, expect, it } from "vitest";
import { rowKind, totals } from "./estimate";

const row = (cells: string[], section = false, guess?: boolean) => ({ cells, section, guess });

describe("estimate rows", () => {
  it("раздел, позиция и итог раздела различаются по ячейкам", () => {
    expect(rowKind(row(["", "Материалы", "", "", "", ""], true))).toBe("section");
    expect(rowKind(row(["1", "Кабель", "м", "10", "45", "450"]))).toBe("line");
    expect(rowKind(row(["2", "Розетка", "шт", "4", "—", "—"]))).toBe("line");
    expect(rowKind(row(["", "Итого", "", "", "", "450"]))).toBe("subtotal");
  });

  it("итоги — по названиям разделов и «Всего», условная сумма — с пометкой; без цен — пусто", () => {
    const rows = [
      row(["", "Материалы", "", "", "", ""], true),
      row(["1", "Кабель", "м", "10", "45", "450"]),
      row(["", "Итого", "", "", "", "450"], false, true),
      row(["", "Работы", "", "", "", ""], true),
      row(["", "Итого", "", "", "", "300"]),
    ];
    expect(totals(rows, ["", "Всего", "", "", "", "750"])).toEqual([
      { name: "Материалы", value: "450", guess: true },
      { name: "Работы", value: "300", guess: false },
      { name: "Всего", value: "750", guess: false },
    ]);
    expect(totals([row(["1", "Кабель", "м", "10"])])).toEqual([]);
  });

  it("старая сборка: примечание после тире в заголовке раздела отбрасывается", () => {
    const rows = [
      row(["", "Материалы — цены пока имитация", "", "", "", ""], true),
      row(["1", "Кабель", "м", "10", "45", "450"]),
      row(["", "Итого", "", "", "", "450"]),
      row(["", "Работы", "", "", "", ""], true),
      row(["", "Итого", "", "", "", "300"]),
    ];
    expect(totals(rows, ["", "Всего", "", "", "", "750"]).map((x) => x.name)).toEqual(["Материалы", "Работы", "Всего"]);
  });
});
