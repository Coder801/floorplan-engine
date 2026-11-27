// Estimate (key estimate of the wiring page, side.estimate_side_table): section rows, items,
// section totals, by cell. A section total has an empty number, a name and a sum (the last cell)

import type { TableRow } from "./types";

export type RowKind = "section" | "subtotal" | "line";

export function rowKind(row: TableRow): RowKind {
  if (row.section) return "section";
  const filled = row.cells.filter(Boolean).length;
  return !row.cells[0] && filled === 2 && !!row.cells[row.cells.length - 1] ? "subtotal" : "line";
}

// One line of the side panel totals: a section or "Total"
export interface EstimateTotal { name: string; value: string }

// Totals for the side panel: sections and "Total" (a bill of quantities without prices has no totals,
// finish materials — a list without prices — have none either). In the table a section total is a
// plain "Total" under its heading; here, in a list, it is named by its section. Builds before
// 2026-11-23 wrote a note into the heading ("Materials — prices are a placeholder"): the part
// after the dash is dropped
export function totals(rows: readonly TableRow[], total?: readonly string[]): EstimateTotal[] {
  const out: EstimateTotal[] = [];
  let section = "";
  for (const r of rows) {
    const kind = rowKind(r);
    if (kind === "section") section = (r.cells[1] ?? "").split(" — ")[0];
    else if (kind === "subtotal") out.push({ name: section || r.cells[1], value: r.cells[r.cells.length - 1] });
  }
  if (total && total[total.length - 1]) out.push({ name: total[1], value: total[total.length - 1] });
  return out;
}
