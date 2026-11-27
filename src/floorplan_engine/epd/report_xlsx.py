"""Estimate report as Excel, from a built .epd: the chosen estimate sections with formulas.

The same data as the PDF report (epd/report.py): the estimate table of the wiring page (key
`estimate`), split into sections by `estimate_blocks`, the same estimate parts (`ESTIMATE_PARTS`;
the plan and the single-line diagram are drawings and do not go to Excel). An estimate that is
not split into rough and finish materials (section `material`) goes in once, with either
materials part. Like out/estimate.xlsx (electrical/estimate/files.py): a row sum is the formula
"qty × price", a section total and "Total" are formulas, the total of a materials section
priced by the placeholder is yellow; a bill of quantities (no prices) has no sums. The look is
quiet, for the client: no Excel grid, thin light rules between rows, a lightly filled column
head, air above each section, a rule above every total; numbers on the right; A4 to page width.
The work scope of the chosen work sections is a second sheet. The same .epd and parts always
give the same table (the file bytes differ: openpyxl stamps the time).
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO
from typing import Any, Literal, get_args

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.worksheet.worksheet import Worksheet

from floorplan_engine.electrical.estimate.files import XLSX_MONEY, XLSX_QTY
from floorplan_engine.electrical.estimate.texts import parse_number, section_title
from floorplan_engine.electrical.estimate.texts import text as estimate_text
from floorplan_engine.epd.report import (
    ESTIMATE_PARTS,
    WORK_SECTIONS,
    EstimateBlock,
    Part,
    estimate_blocks,
    report_filename,
    report_language,
    text,
)
from floorplan_engine.model.texts import Language

XLSX_PARTS: tuple[Part, ...] = tuple(ESTIMATE_PARTS)
# Whose estimate: electrical (the wiring page) or plumbing (the plumbing page, key `estimate` too;
# its sections are materials, not split, and rough work)
Stage = Literal["wiring", "plumbing"]
STAGES: tuple[Stage, ...] = get_args(Stage)
TEXT: dict[str, dict[Language, str]] = {
    "plumbing": {"ru": "Смета сантехники", "uk": "Кошторис сантехніки"},
    "no_plumbing": {
        "ru": "В сборке нет сметы сантехники",
        "uk": "У збірці немає кошторису сантехніки",
    },
}
EXCEL_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Quiet table: ink and muted text, light rules, a light column head (as the PDF report)
INK = "1D2330"
MUTED = "667085"
RULE = "E4E7EC"  # between rows
RULE_STRONG = "C9CED6"  # under the head, above totals
HEAD_FILL = "F2F4F7"
FONT_NAME = "Calibri"
WIDTHS = (6, 50, 8, 11, 13, 15)
# Column alignment: № centred, name on the left with an indent, unit centred, numbers right
ALIGN = ("center", "left", "center", "right", "right", "right")


def xlsx_filename(manifest: dict[str, Any], stage: Stage = "wiring") -> str:
    """The Excel file name: "<project> — <estimate>.xlsx", like the PDF one."""
    if stage == "wiring":
        return report_filename(manifest, XLSX_PARTS).removesuffix(".pdf") + ".xlsx"
    title = TEXT["plumbing"][report_language(manifest)]
    project = str((manifest.get("project") or {}).get("name") or "").strip()
    name = f"{project} — {title}" if project else title
    safe = "".join(" " if c in '/\\:*?"<>|' or ord(c) < 32 else c for c in name)
    return " ".join(safe.split()) + ".xlsx"


def report_xlsx(
    manifest: dict[str, Any],
    page: dict[str, Any] | None,
    parts: Sequence[Part] | None,
    stage: Stage = "wiring",
) -> bytes:
    """The workbook of the chosen estimate parts of the page (others are ignored); a section the
    estimate does not have is a line saying so, no estimate in the build — a line saying so.
    parts None: every section the estimate has, in its order (the plumbing estimate)."""
    language = report_language(manifest)
    project = str((manifest.get("project") or {}).get("name") or "")
    title = text("estimate", language) if stage == "wiring" else TEXT["plumbing"][language]
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = title[:31]
    _sheet(ws)
    ws["A1"] = f"{title}{f' — {project}' if project else ''}"
    ws["A1"].font = _font(size=15, bold=True)
    ws.row_dimensions[1].height = 30
    estimate = (page or {}).get("estimate")
    if not estimate:
        ws.append([])
        missing = (
            text("no_estimate", language) if stage == "wiring" else TEXT["no_plumbing"][language]
        )
        ws.append(["", missing])
        ws.cell(ws.max_row, 2).font = _font(color=MUTED, italic=True)
        return _save(wb)
    columns = [str(c) for c in estimate["columns"]]
    width = len(columns)
    priced = width >= 6
    ws.append([])
    ws.append(columns)
    head_row = ws.max_row
    _row(ws, head_row, width, font=_font(size=9, bold=True, color=MUTED), height=28,
         fill=HEAD_FILL, below=RULE_STRONG, wrap=True)  # fmt: skip
    every = estimate_blocks(estimate, language)
    blocks = {b.section: b for b in every}
    shown: list[EstimateBlock] = []
    subtotals: list[str] = []
    chosen = (
        [(None, every)]
        if parts is None
        else [
            (p, [blocks[s] for s in ESTIMATE_PARTS[p] if s in blocks])
            for p in XLSX_PARTS
            if p in parts
        ]
    )
    for part, found in chosen:
        if not found and part is not None:
            _gap(ws)
            ws.append(["", f"{_section_title(part, language)}: {text('no_section', language)}"])
            _row(ws, ws.max_row, width, font=_font(color=MUTED, italic=True), height=22)
        for block in found:
            if block in shown:  # an estimate not split: one materials section for both
                continue
            shown.append(block)
            total = _block(ws, block, width, priced, language)
            if total is not None:
                subtotals.append(total)
    if priced and subtotals:
        _gap(ws, 14)
        currency = columns[-1].rpartition(", ")[2]
        ws.append(["", f"{estimate_text('total', language)}, {currency}", "", "", "",
                   "=" + "+".join(subtotals)])  # fmt: skip
        grand = ws.max_row
        _row(ws, grand, width, font=_font(size=13, bold=True), height=30, above=RULE_STRONG,
             medium=True)  # fmt: skip
        ws.cell(grand, 6).number_format = XLSX_MONEY
    for letter, w in zip("ABCDEF", WIDTHS[:width], strict=False):
        ws.column_dimensions[letter].width = w
    ws.freeze_panes = f"A{head_row + 1}"
    ws.print_title_rows = f"{head_row}:{head_row}"
    _scope_sheet(wb, shown, language)
    return _save(wb)


def _section_title(part: Part, language: Language) -> str:
    return section_title(ESTIMATE_PARTS[part][0], language)


def _block(
    ws: Worksheet, block: EstimateBlock, width: int, priced: bool, language: Language
) -> str | None:
    """A section: heading, items, its total as a formula; returns the total cell (priced). Finish
    materials (listed) are a bill of quantities: no price, no total, the note in its place."""
    _gap(ws)
    ws.append(["", block.title])
    _row(ws, ws.max_row, width, font=_font(size=11, bold=True), height=24, below=RULE_STRONG)
    first = ws.max_row + 1
    for row in block.rows:
        cells = [str(c) for c in row["cells"]]
        r = ws.max_row + 1
        no = parse_number(cells[0])
        qty = parse_number(cells[3])
        values: list[object] = [int(no) if no is not None else cells[0], cells[1], cells[2],
                                qty if qty is not None else cells[3]]  # fmt: skip
        if priced and not block.listed:
            price = parse_number(cells[4])
            values += [price, f'=IF(E{r}="","",D{r}*E{r})']
        ws.append(values)
        _row(ws, r, width, font=_font(), height=None, below=RULE, wrap=True)
        ws.cell(r, 1).font = _font(color=MUTED)
        ws.cell(r, 4).number_format = XLSX_QTY
        if priced:
            ws.cell(r, 5).number_format = XLSX_MONEY
            ws.cell(r, 6).number_format = XLSX_MONEY
        if row.get("hint"):
            ws.cell(r, 2).comment = Comment(str(row["hint"]), "Shtroba")
    if block.listed:
        ws.append(["", estimate_text("listed", language)])
        _row(ws, ws.max_row, width, font=_font(size=9, color=MUTED, italic=True), height=20)
        return None
    if not priced:
        return None
    last = ws.max_row
    caption = str(block.subtotal["cells"][1]) if block.subtotal else ""
    ws.append(["", caption, "", "", "", f"=SUM(F{first}:F{last})" if last >= first else 0])
    total = ws.max_row
    _row(ws, total, width, font=_font(bold=True), height=24, above=RULE_STRONG)
    ws.cell(total, 6).number_format = XLSX_MONEY
    return f"F{total}"


def _scope_sheet(wb: Workbook, blocks: Sequence[EstimateBlock], language: Language) -> None:
    """What each work of the chosen work sections includes and its result: a second sheet."""
    groups = [
        b for b in blocks if b.section in WORK_SECTIONS and any(r.get("scope") for r in b.rows)
    ]
    if not groups:
        return
    ws = wb.create_sheet(text("appendix", language)[:31])
    _sheet(ws)
    aligns = ("center", "left", "left", "left")
    ws["A1"] = text("appendix", language)
    ws["A1"].font = _font(size=15, bold=True)
    ws.row_dimensions[1].height = 30
    ws.append(["", text("appendix_lead", language)])
    ws.cell(2, 2).font = _font(size=9, color=MUTED)
    ws.append([])
    ws.append(["№", "", text("includes", language), text("result", language)])
    head = ws.max_row
    _row(ws, head, 4, font=_font(size=9, bold=True, color=MUTED), height=28, fill=HEAD_FILL,
         below=RULE_STRONG, aligns=aligns)  # fmt: skip
    for block in groups:
        _gap(ws)
        ws.append(["", block.title])
        _row(ws, ws.max_row, 4, font=_font(size=11, bold=True), height=24, below=RULE_STRONG,
             aligns=aligns)  # fmt: skip
        for row in block.rows:
            scope = row.get("scope")
            if not scope:
                continue
            includes = "; ".join(str(i) for i in scope.get("includes") or [])
            ws.append([str(row["cells"][0]), str(row["cells"][1]), includes,
                       str(scope.get("result") or "")])  # fmt: skip
            _row(ws, ws.max_row, 4, font=_font(), height=None, below=RULE, wrap=True,
                 aligns=aligns, top=True)  # fmt: skip
            ws.cell(ws.max_row, 1).font = _font(color=MUTED)
    for letter, w in zip("ABCD", (6, 40, 60, 40), strict=True):
        ws.column_dimensions[letter].width = w
    ws.freeze_panes = f"A{head + 1}"
    ws.print_title_rows = f"{head}:{head}"


def _sheet(ws: Worksheet) -> None:
    """No Excel grid (the rules are drawn), A4 portrait to the page width, even margins."""
    ws.sheet_view.showGridLines = False
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_margins.left = ws.page_margins.right = 0.5
    ws.page_margins.top = ws.page_margins.bottom = 0.6


def _font(size: float = 10, bold: bool = False, color: str = INK, italic: bool = False) -> Font:
    return Font(name=FONT_NAME, size=size, bold=bold, color=color, italic=italic)


def _row(
    ws: Worksheet,
    r: int,
    width: int,
    font: Font,
    height: float | None,
    fill: str | None = None,
    below: str | None = None,
    above: str | None = None,
    medium: bool = False,
    wrap: bool = False,
    aligns: Sequence[str] = ALIGN,
    top: bool = False,
) -> None:
    """Style a table row across its columns: font, height (None: Excel fits wrapped text),
    a fill, a rule below or above, the column alignment with an indent on the text columns."""
    paint = PatternFill("solid", start_color=fill, end_color=fill) if fill else None
    border = Border(
        bottom=Side(style="thin", color=below) if below else Side(),
        top=Side(style="medium" if medium else "thin", color=above) if above else Side(),
    )
    for col in range(1, width + 1):
        cell = ws.cell(r, col)
        cell.font = font
        horizontal = aligns[col - 1] if col <= len(aligns) else "left"
        cell.alignment = Alignment(
            horizontal=horizontal,
            vertical="top" if top else "center",
            wrap_text=wrap,
            indent=1 if horizontal in ("left", "right") else 0,
        )
        cell.border = border
        if paint is not None:
            cell.fill = paint
    if height is not None:
        ws.row_dimensions[r].height = height


def _gap(ws: Worksheet, height: float = 10) -> None:
    """Air before a section: an empty low row."""
    ws.append([])
    ws.row_dimensions[ws.max_row].height = height


def _save(wb: Workbook) -> bytes:
    # The formulas carry no stored values: the spreadsheet counts them when the file opens
    wb.calculation.fullCalcOnLoad = True
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
