"""Таблицы на листе (мм листа): линии и тексты, без ACAD_TABLE — так их одинаково
открывает любая CAD-программа.

Экспликация помещений: площади — поля AutoCAD от контуров помещений в модели,
итог — поле-сумма; поменяли стену и контур в AutoCAD — таблица пересчитается.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ezdxf.colors import RGB
from ezdxf.document import Drawing
from ezdxf.entities.mtext import MText
from ezdxf.enums import MTextEntityAlignment, TextEntityAlignment
from ezdxf.layouts.base import BaseLayout

from shtroba.draw_plan import RoomArea, add_text
from shtroba.fields import add_area_field, add_area_sum_field
from shtroba.geometry import Vec
from shtroba.layers import (
    A_SHEET,
    A_TEXT,
    TEXT_DIM_MM,
    TEXT_ROOM_MM,
    TEXT_STYLE,
    text_width,
)
from shtroba.schema import Plan
from shtroba.texts import tr
from shtroba.titleblock import LW_THICK, LW_THIN

ROW_H = 8.0
HEADER_H = 12.0
CELL_PAD = 2.0
TITLE_GAP = 3.0
TEXT_GAP = 1.0  # мм листа: запас к ширине текста по метрикам, чтобы он не касался линий


@dataclass(frozen=True)
class Mark:
    """Ячейка с цветным кружком перед текстом: группа щита цветом её линий."""

    text: str
    color: int  # true color, 0xRRGGBB


# Ячейка: готовый текст, текст с цветным кружком или функция, которая заполнит
# MTEXT-носитель (поле AutoCAD)
Cell = str | Mark | Callable[[MText], None]
MARK_R = 1.1  # радиус кружка на листе, мм


@dataclass(frozen=True)
class Column:
    title: str
    width: float
    align: str = "center"  # center | left


@dataclass(frozen=True)
class Table:
    title: str
    columns: tuple[Column, ...]
    rows: tuple[tuple[Cell, ...], ...]
    total: tuple[Cell, ...] | None = None  # итоговая строка, отделена основной линией
    row_h: float = ROW_H  # высота строки; длинные ведомости (смета) — плотнее
    header_h: float = HEADER_H

    @property
    def width(self) -> float:
        return sum(c.width for c in self.columns)

    @property
    def height(self) -> float:
        n = len(self.rows) + (1 if self.total else 0)
        return TEXT_ROOM_MM + TITLE_GAP + self.header_h + n * self.row_h


def _line(layout: BaseLayout, a: Vec, b: Vec, thick: bool) -> None:
    layout.add_line(
        a.as_tuple(),
        b.as_tuple(),
        dxfattribs={"layer": A_SHEET.name, "lineweight": LW_THICK if thick else LW_THIN},
    )


def _cell(layout: BaseLayout, cell: Cell, col: Column, x0: float, y_mid: float) -> None:
    if isinstance(cell, Mark):
        x = x0 + CELL_PAD + MARK_R
        hatch = layout.add_hatch(dxfattribs={"layer": A_TEXT.name, "true_color": cell.color})
        hatch.set_solid_fill(rgb=_rgb(cell.color))
        hatch.paths.add_edge_path().add_arc((x, y_mid), MARK_R, 0, 360)
        at = Vec(x + MARK_R + CELL_PAD / 2, y_mid)
        add_text(layout, cell.text, at, TEXT_DIM_MM, A_TEXT.name, align=_LEFT, scale=1.0)
        return
    if isinstance(cell, str):
        if col.align == "left":
            at, align = Vec(x0 + CELL_PAD, y_mid), TextEntityAlignment.MIDDLE_LEFT
        else:
            at, align = Vec(x0 + col.width / 2, y_mid), TextEntityAlignment.MIDDLE_CENTER
        add_text(layout, cell, at, TEXT_DIM_MM, A_TEXT.name, align=align, scale=1.0)
        return
    mtext = layout.add_mtext(
        "", dxfattribs={"layer": A_TEXT.name, "style": TEXT_STYLE, "char_height": TEXT_DIM_MM}
    )
    mtext.set_location(
        (x0 + col.width / 2, y_mid), attachment_point=MTextEntityAlignment.MIDDLE_CENTER
    )
    cell(mtext)


_LEFT = TextEntityAlignment.MIDDLE_LEFT


def _rgb(color: int) -> RGB:
    return RGB((color >> 16) & 255, (color >> 8) & 255, color & 255)


def draw_table(layout: BaseLayout, table: Table, top_left: Vec) -> None:
    """Название над таблицей, шапка, строки, итог; основные линии — контур и шапка."""
    x0, y = top_left.x, top_left.y
    title_at = Vec(x0 + table.width / 2, y - TEXT_ROOM_MM / 2)
    add_text(layout, table.title, title_at, TEXT_ROOM_MM, A_TEXT.name, scale=1.0)
    y -= TEXT_ROOM_MM + TITLE_GAP
    top = y
    xs = [x0]
    for col in table.columns:
        xs.append(xs[-1] + col.width)
    rows: list[tuple[tuple[Cell, ...], float]] = [
        (tuple(c.title for c in table.columns), table.header_h),
        *((r, table.row_h) for r in table.rows),
    ]
    if table.total is not None:
        rows.append((table.total, table.row_h))
    for k, (cells, h) in enumerate(rows):
        # Основная линия — над таблицей, под шапкой и над итогом
        thick = k == 0 or k == 1 or (table.total is not None and k == len(rows) - 1)
        _line(layout, Vec(x0, y), Vec(xs[-1], y), thick)
        for cell, col, cx in zip(cells, table.columns, xs[:-1], strict=True):
            _cell(layout, cell, col, cx, y - h / 2)
        y -= h
    _line(layout, Vec(x0, y), Vec(xs[-1], y), True)
    for x in xs:
        _line(layout, Vec(x, top), Vec(x, y), True)


def name_width(names: list[str]) -> float:
    """Ширина колонки наименований под самый длинный текст, мм листа (по метрикам шрифта)."""
    longest = max(text_width(n, TEXT_DIM_MM) for n in names)
    return max(40.0, longest + 2 * CELL_PAD + TEXT_GAP)


def room_schedule(plan: Plan, areas: dict[str, RoomArea]) -> Table:
    """Экспликация помещений: №, наименование, площадь (поле), итог (поле-сумма)."""
    lang = plan.language
    columns = (
        Column(tr("schedule_no", lang), 12.0),
        Column(tr("schedule_name", lang), name_width([r.name for r in plan.rooms]), "left"),
        Column(tr("schedule_area", lang), 25.0),
    )

    def area_cell(area: RoomArea) -> Cell:
        return lambda m: add_area_field(_doc(m), m, area.contour, area.area_mm2)

    rows = tuple(
        (str(k), room.name, area_cell(areas[room.id])) for k, room in enumerate(plan.rooms, 1)
    )

    def total_cell(m: MText) -> None:
        targets = [(areas[r.id].contour, areas[r.id].area_mm2) for r in plan.rooms]
        add_area_sum_field(_doc(m), m, targets)

    return Table(
        tr("schedule_title", lang),
        columns,
        rows,
        total=("", tr("schedule_total", lang), total_cell),
    )


def _doc(entity: MText) -> Drawing:
    doc = entity.doc
    assert doc is not None
    return doc
