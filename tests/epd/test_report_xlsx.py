from __future__ import annotations

from io import BytesIO
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from floorplan_engine.epd.report_xlsx import XLSX_PARTS, report_xlsx, xlsx_filename

MANIFEST: dict[str, Any] = {"project": {"name": "Кв 1", "language": "ru"}, "pages": []}


def _row(*cells: str, **extra: Any) -> dict[str, Any]:
    return {"cells": list(cells), **extra}


ESTIMATE: dict[str, Any] = {
    "columns": ["№", "Наименование", "Ед.", "Кол.", "Цена, грн", "Сумма, грн"],
    "align": ["center", "left", "center", "center", "center", "center"],
    "rows": [
        _row("", "Черновые материалы", "", "", "", "", section=True),
        _row("1", "Кабель ВВГнг 3×1,5", "м", "10,5", "45", "472,5", hint="цена сервиса"),
        _row("2", "Гофра", "м", "4", "—", "—"),
        _row("", "Итого", "", "", "", "472,5", guess=True),
        _row("", "Черновые работы", "", "", "", "", section=True),
        _row(
            "1",
            "Прокладка кабеля",
            "м",
            "10",
            "34",
            "340",
            scope={"includes": ["разметка", "фиксация"], "result": "кабель закреплён"},
        ),
        _row("", "Итого", "", "", "", "340"),
        _row("", "Чистовые работы", "", "", "", "", section=True),
        _row("1", "Установка механизмов", "шт", "2", "100", "200"),
        _row("", "Итого", "", "", "", "200"),
    ],
}


def _sheets(data: bytes) -> list[Worksheet]:
    wb = load_workbook(BytesIO(data))
    return [wb[n] for n in wb.sheetnames]


def _values(ws: Worksheet) -> list[list[object]]:
    return [list(r) for r in ws.iter_rows(values_only=True)]


def test_only_chosen_sections_with_formulas() -> None:
    [ws] = _sheets(report_xlsx(MANIFEST, {"estimate": ESTIMATE}, ["material_rough", "work_finish"]))
    rows = _values(ws)
    names = [r[1] for r in rows]
    assert "Черновые материалы" in names and "Чистовые работы" in names
    assert "Черновые работы" not in names and "Прокладка кабеля" not in names
    cable = rows[names.index("Кабель ВВГнг 3×1,5")]
    assert cable[3] == 10.5 and cable[4] == 45 and str(cable[5]).startswith("=IF(E")
    assert rows[names.index("Гофра")][4] is None  # no price: empty, the sum stays empty
    total = rows[names.index("Всего, грн")]
    assert str(total[5]).count("+") == 1  # two section totals
    assert ws.cell(names.index("Кабель ВВГнг 3×1,5") + 1, 2).comment is not None


def test_missing_section_and_work_scope_sheet() -> None:
    sheets = _sheets(
        report_xlsx(MANIFEST, {"estimate": ESTIMATE}, ["material_finish", "work_rough"])
    )
    assert len(sheets) == 2
    first = [r[1] for r in _values(sheets[0])]
    assert "Чистовые материалы: В смете нет этого раздела" in first
    scope = _values(sheets[1])
    assert ["1", "Прокладка кабеля", "разметка; фиксация", "кабель закреплён"] in scope


def test_bill_of_quantities_and_no_estimate() -> None:
    bill = {
        "columns": ["№", "Наименование", "Ед.", "Кол."],
        "align": ["center", "left", "center", "center"],
        "rows": [
            _row("", "Черновые материалы", "", "", section=True),
            _row("1", "Кабель", "м", "3"),
        ],
    }
    [ws] = _sheets(report_xlsx(MANIFEST, {"estimate": bill}, XLSX_PARTS))
    rows = _values(ws)
    assert [1, "Кабель", "м", 3] in [r[:4] for r in rows]
    assert not any(str(r[1]).startswith("Всего") for r in rows)
    [empty] = _sheets(report_xlsx(MANIFEST, None, XLSX_PARTS))
    assert [None, "В сборке нет сметы электрики"] in [r[:2] for r in _values(empty)]


def test_filename() -> None:
    assert xlsx_filename(MANIFEST) == "Кв 1 — Смета электрики.xlsx"


def test_plumbing_goes_whole_with_its_title() -> None:
    plumbing = {
        "columns": ESTIMATE["columns"],
        "align": ESTIMATE["align"],
        "rows": [
            _row("", "Материалы", "", "", "", "", section=True),
            _row("1", "Труба PE-Xa 16", "м", "20", "50", "1 000"),
            _row("", "Итого", "", "", "", "1 000"),
            _row("", "Черновые работы", "", "", "", "", section=True),
            _row("1", "Опрессовка", "шт", "1", "1 500", "1 500"),
            _row("", "Итого", "", "", "", "1 500"),
        ],
    }
    [ws] = _sheets(report_xlsx(MANIFEST, {"estimate": plumbing}, None, "plumbing"))
    rows = _values(ws)
    names = [r[1] for r in rows]
    assert rows[0][0] == "Смета сантехники — Кв 1"
    assert "Материалы" in names and "Черновые работы" in names
    assert not any("нет этого раздела" in str(n) for n in names)  # no lines for absent sections
    assert str(rows[names.index("Всего, грн")][5]).count("+") == 1
    assert xlsx_filename(MANIFEST, "plumbing") == "Кв 1 — Смета сантехники.xlsx"
    [empty] = _sheets(report_xlsx(MANIFEST, None, None, "plumbing"))
    assert [None, "В сборке нет сметы сантехники"] in [r[:2] for r in _values(empty)]
