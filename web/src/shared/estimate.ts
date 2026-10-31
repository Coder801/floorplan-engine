// Смета (ключ estimate страницы проводки, side.estimate_side_table): строки раздела, позиции,
// итоги разделов — по ячейкам. Итог раздела — пустой номер, название и сумма (последняя ячейка)

import type { TableRow } from "./types";

export type RowKind = "section" | "subtotal" | "line";

export function rowKind(row: TableRow): RowKind {
  if (row.section) return "section";
  const filled = row.cells.filter(Boolean).length;
  return !row.cells[0] && filled === 2 && !!row.cells[row.cells.length - 1] ? "subtotal" : "line";
}

// Итоги для боковой панели: разделы и «Всего» (у ведомости объёмов без цен итогов нет)
export function totals(rows: readonly TableRow[], total?: readonly string[]): [string, string][] {
  const out = rows.filter((r) => rowKind(r) === "subtotal").map((r): [string, string] => [r.cells[1], r.cells[r.cells.length - 1]]);
  if (total && total[total.length - 1]) out.push([total[1], total[total.length - 1]]);
  return out;
}
