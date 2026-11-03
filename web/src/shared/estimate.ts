// Estimate (key estimate of the wiring page, side.estimate_side_table): section rows, items,
// section totals, by cell. A section total has an empty number, a name and a sum (the last cell)

import type { TableRow } from "./types";

export type RowKind = "section" | "subtotal" | "line";

export function rowKind(row: TableRow): RowKind {
  if (row.section) return "section";
  const filled = row.cells.filter(Boolean).length;
  return !row.cells[0] && filled === 2 && !!row.cells[row.cells.length - 1] ? "subtotal" : "line";
}

// Totals for the side panel: sections and "Total" (a bill of quantities without prices has no totals)
export function totals(rows: readonly TableRow[], total?: readonly string[]): [string, string][] {
  const out = rows.filter((r) => rowKind(r) === "subtotal").map((r): [string, string] => [r.cells[1], r.cells[r.cells.length - 1]]);
  if (total && total[total.length - 1]) out.push([total[1], total[total.length - 1]]);
  return out;
}
