"""Печать: деление таблиц по строкам, листы-продолжения на малом формате, PDF-альбом и
проверка листа перед печатью."""

from __future__ import annotations

from pathlib import Path

import pypdfium2
from ezdxf.document import Drawing

from floorplan_engine.drawing.layers import MIN_TEXT_MM
from floorplan_engine.drawing.tables import Column, Table
from floorplan_engine.model.geometry import Contour
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.sheets.document import build_project_document
from floorplan_engine.sheets.layout import Panel, paginate, split_table, table_panel
from floorplan_engine.sheets.preview import sheet_layouts
from floorplan_engine.sheets.printing import SheetCheck, check_sheets, write_album
from floorplan_engine.validation.issues import parse_model
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

TABLE = Table(
    "Смета",
    (Column("№", 10.0), Column("Позиция", 60.0)),
    tuple((str(k), f"позиция {k}") for k in range(1, 41)),
    total=("", "Всего"),
)


def test_split_table_keeps_rows_header_and_total() -> None:
    head = Table(TABLE.title, TABLE.columns, ()).height
    rest = head + 10 * TABLE.row_h
    parts = split_table(TABLE, rest, rest)
    assert parts is not None and len(parts) > 1
    assert all(p.height <= rest + 1e-9 for p in parts)
    assert sum(len(p.rows) for p in parts) == len(TABLE.rows)  # строки не теряются
    assert parts[0].title == "Смета" and all(p.title == "" for p in parts[1:])
    assert [p.total is not None for p in parts] == [False] * (len(parts) - 1) + [True]


def test_split_table_skips_short_lead() -> None:
    """В остатке колонки меньше MIN_LEAD_ROWS строк — таблица начинается с полной высоты."""
    head = Table(TABLE.title, TABLE.columns, ()).height
    parts = split_table(TABLE, head + 2 * TABLE.row_h, head + 20 * TABLE.row_h)
    assert parts is not None and len(parts[0].rows) > 2
    assert split_table(TABLE, head, head + TABLE.row_h) is None  # две строки не входят


def test_paginate_columns_then_pages() -> None:
    def box(w: float, h: float) -> Panel:
        return Panel(w, h, lambda psp, tl: None)

    pages = paginate([box(50, 80), box(50, 80), box(50, 80)], 120, 100)
    assert pages is not None and len(pages) == 2  # две колонки на странице, третья — дальше
    assert pages[0].width <= 120
    long = paginate([table_panel(TABLE)], 200, 80)
    assert long is not None and all(p.height <= 80 for p in long)
    assert paginate([box(300, 10)], 120, 100) is None  # шире страницы


def _project(points: int) -> tuple[Plan, dict[str, Contour], Electrical]:
    plan = make_plan([{"length": 6000}, {"length": 9000}, {"length": 6000}, {"length": 9000}])
    _, contours = validate_plan(plan)
    point = {"room": "r", "wall": "w2", "type": "socket", "height": 300, "group": "QF1"}
    elec, issues = parse_model(
        Electrical,
        {
            "points": [
                {"id": f"s{k}", "offset": 100 * k, "note": f"прибор {k}", **point}
                for k in range(1, points + 1)
            ],
            "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
        },
        "e.yaml",
    )
    assert elec is not None, issues
    return plan, contours, elec


def test_small_format_moves_tables_to_continuation() -> None:
    plan, contours, elec = _project(60)
    sheet = plan.sheet.model_copy(update={"format": "A4"})
    doc = build_project_document(plan.model_copy(update={"sheet": sheet}), contours, elec)
    names = [lay.name for lay in sheet_layouts(doc)]
    assert any("(продолжение)" in n for n in names)
    checks = {c.tab: c for c in check_sheets(doc)}
    assert not checks["03 Электрика (продолжение)"].empty
    assert all(c.min_text is None or c.min_text >= MIN_TEXT_MM - 1e-6 for c in checks.values())
    # Что не влезло даже на продолжение (аппараты щита шире A4), не пропадает молча
    assert all(c.warnings() for c in checks.values() if c.empty or c.overflow > 0.5)


def test_check_warns_about_small_text_overflow_and_empty() -> None:
    assert SheetCheck("01 План", 1.8, 0.0).warnings() == []
    warnings = SheetCheck("04 Щит", 1.3, 12.0, empty=True).warnings()
    assert len(warnings) == 3 and "1.3 мм" in warnings[0]


def test_album_pages_have_paper_size(tmp_path: Path) -> None:
    plan, contours, elec = _project(4)
    doc: Drawing = build_project_document(plan, contours, elec)
    pdf = write_album(doc, tmp_path / "album.pdf", "тест")
    layouts = sheet_layouts(doc)
    document = pypdfium2.PdfDocument(pdf)
    try:
        assert len(document) == len(layouts)
        w, h = document[0].get_size()
        paper = layouts[0].dxf_layout.dxf
        assert abs(w / 72 * 25.4 - paper.paper_width) < 0.5
        assert abs(h / 72 * 25.4 - paper.paper_height) < 0.5
    finally:
        document.close()
