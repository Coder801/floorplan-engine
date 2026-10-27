"""Таблицы листов для боковой панели просмотра: те же данные, что в таблицах на листе,
текстом, и у каждой строки — объекты чертежа (ключи «тип:id», как в XDATA), к которым она
относится. Наведение на объект подсвечивает его строку, наведение на строку — объекты.

Здесь же — какие объекты «свои» для темы листа: подсказки на листе проводки — только
у проводки, на плане — только у плана.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from floorplan_engine.draw_electrical import group_colors
from floorplan_engine.draw_wiring import wiring_notes, wiring_table
from floorplan_engine.estimate import PriceList, build_estimate, estimate_table
from floorplan_engine.fields import format_area
from floorplan_engine.geometry import Contour
from floorplan_engine.groups import group_rows, groups_table
from floorplan_engine.schema import Electrical, Plan
from floorplan_engine.specification import specification_table
from floorplan_engine.symbols import LEGEND_ORDER, symbol_key
from floorplan_engine.tables import Mark, Table
from floorplan_engine.texts import Language, tr
from floorplan_engine.wiring import Wiring

# Тема листа (sheets.SHEET_SLUGS) → типы объектов, у которых на нём есть подсказка
STAGE_OBJECTS: dict[str, frozenset[str]] = {
    "plan": frozenset({"room", "wall", "dimension", "opening"}),
    "electrical": frozenset({"point", "label", "board", "cable", "led_strip"}),
    "wiring": frozenset({"wire", "box", "board"}),
}

TEXT: dict[str, dict[str, str]] = {
    "symbols": {"ru": "Условные обозначения", "uk": "Умовні позначення"},
    "symbol": {"ru": "Обозначение", "uk": "Позначення"},
    "qty": {"ru": "Кол.", "uk": "Кільк."},
}


def text(key: str, language: Language) -> str:
    return TEXT[key][language]


@dataclass(frozen=True)
class SideRow:
    cells: tuple[str, ...]
    keys: tuple[str, ...] = ()  # объекты чертежа этой строки
    section: bool = False  # заголовок раздела (смета): одна непустая ячейка
    color: str | None = None  # цвет группы «#rrggbb» — кружок у первой ячейки

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"cells": list(self.cells)}
        if self.color:
            out["color"] = self.color
        if self.keys:
            out["keys"] = list(self.keys)
        if self.section:
            out["section"] = True
        return out


@dataclass(frozen=True)
class SideTable:
    title: str
    columns: tuple[str, ...]
    align: tuple[str, ...]  # center | left, как на листе
    rows: tuple[SideRow, ...]
    total: tuple[str, ...] | None = None
    notes: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "title": self.title,
            "columns": list(self.columns),
            "align": list(self.align),
            "rows": [r.as_dict() for r in self.rows],
        }
        if self.total is not None:
            out["total"] = list(self.total)
        if self.notes:
            out["notes"] = list(self.notes)
        return out


def from_table(
    table: Table, keys: Sequence[tuple[str, ...]] = (), notes: Sequence[str] = ()
) -> SideTable:
    """Таблица листа текстом. Ячейки-поля AutoCAD (площади) сюда не попадают — для них
    своя сборка (room_table)."""

    def cells(row: Sequence[object]) -> tuple[str, ...]:
        assert all(isinstance(c, str | Mark) for c in row), "ячейка-поле: соберите отдельно"
        return tuple(c.text if isinstance(c, Mark) else str(c) for c in row)

    rows = []
    for k, row in enumerate(table.rows):
        texts = cells(row)
        mark = next((c for c in row if isinstance(c, Mark)), None)
        rows.append(
            SideRow(
                texts,
                keys[k] if k < len(keys) else (),
                section=sum(1 for c in texts if c) == 1 and not texts[0],
                color=f"#{mark.color:06x}" if mark is not None else None,
            )
        )
    return SideTable(
        table.title,
        tuple(c.title for c in table.columns),
        tuple(c.align for c in table.columns),
        tuple(rows),
        cells(table.total) if table.total is not None else None,
        tuple(notes),
    )


def room_table(plan: Plan, contours: dict[str, Contour]) -> SideTable:
    """Экспликация: те же строки, что на листе; площадь — как покажет поле AutoCAD."""
    lang = plan.language
    rows = []
    total = 0.0
    for k, room in enumerate(plan.rooms, 1):
        contour = contours[room.id]
        area = contour.area_m2 * 1e6
        total += area
        keys = [f"room:{room.id}"]
        for seg in contour.segments:
            keys += [f"wall:{room.id}.{seg.id}", f"dimension:{room.id}.{seg.id}"]
        keys += [f"opening:{op.id}" for op in room.openings]
        rows.append(SideRow((str(k), room.name, format_area(area)), tuple(keys)))
    return SideTable(
        tr("schedule_title", lang),
        (tr("schedule_no", lang), tr("schedule_name", lang), tr("schedule_area", lang)),
        ("center", "left", "center"),
        tuple(rows),
        ("", tr("schedule_total", lang), format_area(total)),
    )


def legend_tables(elec: Electrical, language: Language) -> list[SideTable]:
    """Условные обозначения с количеством и группы: строка → точки, кабели, щит."""
    by_symbol: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for p in elec.points:
        key = symbol_key(p)
        by_symbol.setdefault(key, []).append(f"point:{p.id}")
        counts[key] = counts.get(key, 0) + p.count
    if elec.board is not None:
        by_symbol["board"] = ["board:board"]
        counts["board"] = 1
    symbols = tuple(
        SideRow((tr(f"symbol_{k}", language), str(counts[k])), tuple(by_symbol[k]))
        for k in LEGEND_ORDER
        if k in by_symbol
    )
    out = [
        SideTable(
            text("symbols", language),
            (text("symbol", language), text("qty", language)),
            ("left", "center"),
            symbols,
        )
    ]
    return out


def group_side_table(plan: Plan, elec: Electrical) -> SideTable | None:
    """Группы щита: строка → точки и кабели группы."""
    built = groups_table(plan, elec)
    if built is None:
        return None
    table, notes = built
    keys = [
        tuple([f"point:{p}" for p in r.point_ids] + [f"cable:{c}" for c in r.cable_ids])
        for r in group_rows(plan, elec)
    ]
    return from_table(table, keys, notes)


def wiring_tables(
    wiring: Wiring, elec: Electrical, language: Language, prices: PriceList | None
) -> list[SideTable]:
    """Кабели по группам (строка → линии и коробки группы) и смета или ведомость объёмов."""
    table = wiring_table(wiring, language, group_colors(elec))
    keys = []
    for row in table.rows:
        first = row[0]
        group = first.text if isinstance(first, Mark) else first
        runs = [f"wire:{r.id}" for r in wiring.runs if r.group == group]
        boxes = [f"box:{b.id}" for b in wiring.boxes if b.group == group]
        keys.append(tuple(runs + boxes))
    est = build_estimate(wiring, elec, prices or PriceList(), language)
    sheet = estimate_table(est, language, priced=prices is not None)
    return [
        from_table(table, keys, wiring_notes(wiring, language)),
        from_table(sheet),
    ]


def side_tables(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical | None,
    wiring: Wiring | None,
    prices: PriceList | None = None,
) -> dict[str, list[SideTable]]:
    """Таблицы боковой панели по теме листа (plan / electrical / wiring)."""
    lang = plan.language
    out = {"plan": [room_table(plan, contours)]}
    if elec is not None:
        tables = legend_tables(elec, lang)
        groups = group_side_table(plan, elec)
        if groups is not None:
            tables.insert(0, groups)
        spec = specification_table(elec, lang)
        if spec is not None:
            tables.append(from_table(spec))
        out["electrical"] = tables
        if wiring is not None:
            out["wiring"] = wiring_tables(wiring, elec, lang, prices)
    return out
