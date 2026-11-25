"""Electrical estimate files: out/estimate.md, out/estimate.csv and out/estimate.xlsx (Excel with
formulas: change a price or a quantity and the sums recalculate). The total of a materials
section is marked as provisional while material prices are a placeholder (estimate_texts).
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

from floorplan_engine.electrical.estimate import Estimate
from floorplan_engine.electrical.estimate_items import MATERIAL_SECTIONS, SECTIONS
from floorplan_engine.electrical.estimate_texts import (
    PROVISIONAL_MARK,
    format_number,
    provisional,
    section_title,
    text,
)
from floorplan_engine.electrical.price_list import PRICES_FILE
from floorplan_engine.model.texts import Language

ESTIMATE_MD = "estimate.md"
ESTIMATE_CSV = "estimate.csv"
ESTIMATE_XLSX = "estimate.xlsx"
XLSX_MONEY = "#,##0.00"
XLSX_QTY = "#,##0.0##"
XLSX_EDIT_FILL = "FFF4D6"  # cells edited by hand: price and quantity
XLSX_GUESS_FILL = "FFE066"  # provisional amount: total of materials priced by the placeholder


def write_markdown(
    est: Estimate,
    path: Path,
    title: str,
    notes: list[str],
    language: Language,
    tail: Sequence[str] = (),
) -> Path:
    """Estimate in Markdown; tail — lines after the total (the agreed terms, terms.py)."""

    def t(key: str, **values: object) -> str:
        return text(key, language, **values)

    out = [f"# {title}", ""]
    for section in SECTIONS:
        rows = [ln for ln in est.lines if ln.section == section]
        if not rows:
            continue
        out += [
            f"## {section_title(section, language)}",
            "",
            t("head", c=est.currency),
            "|---|---|---|---|---:|---:|",
        ]
        for k, ln in enumerate(rows, 1):
            price = format_number(ln.price) if ln.price is not None else t("no_price")
            total = format_number(ln.total) if ln.total is not None else "—"
            qty = format_number(ln.qty, 1).removesuffix(",0")
            out.append(f"| {k} | {ln.name} | {ln.unit} | {qty} | {price} | {total} |")
        mark = PROVISIONAL_MARK if provisional(section, est.has_prices) else ""
        amount = f"**{format_number(est.subtotal(section))}**{mark}"
        out += [f"| | **{t('subtotal')}** | | | | {amount} |", ""]
    out += [f"**{t('total')}: {format_number(est.total)} {est.currency}**", ""]
    out += tail
    if est.unpriced:
        out += [t("unpriced", n=est.unpriced, f=PRICES_FILE), ""]
    out += [f"- {n}" for n in notes]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def write_csv(est: Estimate, path: Path) -> Path:
    """CSV for Excel: UTF-8 with BOM, ";" separator, decimal comma; section is the section
    (material_rough, material_finish, rough, finish; material in an estimate that is not split)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["section", "key", "name", "unit", "qty", "price", "total"])
        for ln in est.lines:
            w.writerow(
                [
                    ln.section,
                    ln.key,
                    ln.name,
                    ln.unit,
                    f"{ln.qty:g}".replace(".", ","),
                    "" if ln.price is None else f"{ln.price:g}".replace(".", ","),
                    "" if ln.total is None else f"{ln.total:.2f}".replace(".", ","),
                ]
            )
    return path


def write_xlsx(
    est: Estimate,
    path: Path,
    title: str,
    notes: list[str],
    language: Language,
    extra: Callable[[Workbook], None] | None = None,
    tail: Callable[[Worksheet, Mapping[str, str]], None] | None = None,
) -> Path:
    """Estimate in Excel: sections, row sum as a formula "qty × price", section totals and "Total"
    as formulas, prices and quantities highlighted (they get edited), the total of a materials
    section in yellow while it is provisional (provisional). An item without a price has
    an empty price with a note; once a price is entered it counts in the totals. extra adds its
    own sheets after the estimate (the work scope, work_scope.scope_sheet); tail adds rows after
    "Total" (the agreed terms, terms.terms_sheet_tail) and gets the cells of the section
    totals and of "Total" by name."""

    def t(key: str, **values: object) -> str:
        return text(key, language, **values)

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = t("sheet_title")[:31]
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14)
    heads = [
        t("col_no"),
        t("col_name"),
        t("col_unit"),
        t("col_qty"),
        t("col_price", c=est.currency),
        t("col_sum", c=est.currency),
        "key",
    ]
    ws.append([])
    ws.append(heads)
    head_row = ws.max_row
    for cell in ws[head_row]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    edit = PatternFill("solid", start_color=XLSX_EDIT_FILL, end_color=XLSX_EDIT_FILL)
    guess = PatternFill("solid", start_color=XLSX_GUESS_FILL, end_color=XLSX_GUESS_FILL)
    grey = Font(color="999999", size=8)
    subtotals: dict[str, str] = {}
    for section in SECTIONS:
        rows = [ln for ln in est.lines if ln.section == section]
        if not rows:
            continue
        ws.append(["", section_title(section, language)])
        ws.cell(ws.max_row, 2).font = Font(bold=True)
        first = ws.max_row + 1
        for k, ln in enumerate(rows, 1):
            r = ws.max_row + 1
            ws.append([k, ln.name, ln.unit, ln.qty, ln.price, f'=IF(E{r}="","",D{r}*E{r})', ln.key])
            ws.cell(r, 4).number_format = XLSX_QTY
            ws.cell(r, 5).number_format = XLSX_MONEY
            ws.cell(r, 6).number_format = XLSX_MONEY
            ws.cell(r, 4).fill = edit
            ws.cell(r, 5).fill = edit
            ws.cell(r, 7).font = grey
            if ln.hint:
                ws.cell(r, 2).comment = Comment(ln.hint, "Shtroba")
            if ln.price is None:
                ws.cell(r, 5).comment = Comment(t("no_price"), "Shtroba")
        last = ws.max_row
        ws.append(["", t("subtotal"), "", "", "", f"=SUM(F{first}:F{last})"])
        total_row = ws.max_row
        ws.cell(total_row, 2).font = Font(bold=True)
        ws.cell(total_row, 6).font = Font(bold=True)
        ws.cell(total_row, 6).number_format = XLSX_MONEY
        if provisional(section, est.has_prices):
            ws.cell(total_row, 6).fill = guess
        subtotals[section] = f"F{total_row}"
    ws.append([])
    ws.append(
        [
            "",
            f"{t('total')}, {est.currency}",
            "",
            "",
            "",
            "=" + "+".join(subtotals.values()) if subtotals else 0,
        ]
    )
    grand = ws.max_row
    for col in (2, 6):
        ws.cell(grand, col).font = Font(bold=True, size=12)
    ws.cell(grand, 6).number_format = XLSX_MONEY
    if tail is not None:
        # "material" for the tail is all materials, whatever sections they are split into
        parts = [subtotals[s] for s in MATERIAL_SECTIONS if s in subtotals]
        cells = {**subtotals, "total": f"F{grand}"}
        if parts:
            cells["material"] = parts[0] if len(parts) == 1 else f"({'+'.join(parts)})"
        tail(ws, cells)
    ws.append([])
    if est.unpriced:
        ws.append(["", t("unpriced", n=est.unpriced, f=PRICES_FILE)])
    for note in notes:
        ws.append(["", note])
    for letter, width in zip("ABCDEFG", (5, 48, 7, 10, 12, 14, 18), strict=True):
        ws.column_dimensions[letter].width = width
    ws.freeze_panes = f"A{head_row + 1}"
    if extra is not None:
        extra(wb)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
