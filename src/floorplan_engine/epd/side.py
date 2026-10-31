"""Таблицы листов для боковой панели просмотра: те же данные, что в таблицах на листе,
текстом, и у каждой строки — объекты чертежа (ключи «тип:id», как в XDATA), к которым она
относится. Наведение на объект подсвечивает его строку, наведение на строку — объекты.

Здесь же — какие объекты «свои» для темы листа: подсказки на листе проводки — только
у проводки, на плане — только у плана.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from floorplan_engine.drawing.fields import format_area
from floorplan_engine.drawing.lighting import switch_rows, switch_table
from floorplan_engine.drawing.panel import ASSUMED, devices_table, panel_notes
from floorplan_engine.drawing.schedules import (
    estimate_table,
    groups_table,
    points_table,
)
from floorplan_engine.drawing.symbols import LEGEND_ORDER
from floorplan_engine.drawing.tables import Mark, Table
from floorplan_engine.drawing.wiring import wiring_notes
from floorplan_engine.electrical.anchors import symbol_key
from floorplan_engine.electrical.estimate import PRICES_FILE, PriceList, build_estimate
from floorplan_engine.electrical.estimate import text as estimate_text
from floorplan_engine.electrical.groups import group_colors, group_rows
from floorplan_engine.electrical.groups import text as groups_text
from floorplan_engine.electrical.panel import BoardPanel, build_panel, color_of
from floorplan_engine.electrical.point_numbers import point_rows
from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.model.geometry import Contour
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.model.texts import Language, tr

# Тема листа (sheets.SHEET_SLUGS) → типы объектов, у которых на нём есть подсказка
STAGE_OBJECTS: dict[str, frozenset[str]] = {
    "plan": frozenset({"room", "wall", "dimension", "opening"}),
    "electrical": frozenset({"point", "label", "board", "cable", "led_strip"}),
    "lighting": frozenset({"point", "led_strip"}),
    "wiring": frozenset({"wire", "box", "board"}),
    "panel": frozenset({"device", "board"}),
    "elevations": frozenset({"elevation"}),
}

TEXT: dict[str, dict[str, str]] = {
    "symbols": {"ru": "Условные обозначения", "uk": "Умовні позначення"},
    "symbol": {"ru": "Обозначение", "uk": "Позначення"},
    "qty": {"ru": "Кол.", "uk": "Кільк."},
    "consumers": {"ru": "Роспись потребителей", "uk": "Розпис споживачів"},
    "group": {"ru": "Группа", "uk": "Група"},
    "consumer": {"ru": "Потребитель", "uk": "Споживач"},
    "room": {"ru": "Помещение", "uk": "Приміщення"},
    "watts": {"ru": "P, Вт", "uk": "P, Вт"},
    "total": {"ru": "Установленная", "uk": "Встановлена"},
}


def text(key: str, language: Language) -> str:
    return TEXT[key][language]


@dataclass(frozen=True)
class SideRow:
    cells: tuple[str, ...]
    keys: tuple[str, ...] = ()  # объекты чертежа этой строки
    section: bool = False  # заголовок раздела (смета): одна непустая ячейка
    color: str | None = None  # цвет группы «#rrggbb» — кружок у первой ячейки
    hint: str | None = None  # пояснение к строке (смета): значок «i» у наименования

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"cells": list(self.cells)}
        if self.hint:
            out["hint"] = self.hint
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


def drop_column(table: SideTable, index: int) -> SideTable:
    """Таблица без колонки index; подпись итога из неё переходит в первую ячейку итога."""

    def cut(cells: Sequence[str]) -> tuple[str, ...]:
        return tuple(c for k, c in enumerate(cells) if k != index)

    total = None
    if table.total is not None:
        total = cut(table.total)
        if not total[0] and table.total[index]:
            total = (table.total[index], *total[1:])
    return replace(
        table,
        columns=cut(table.columns),
        align=cut(table.align),
        rows=tuple(replace(r, cells=cut(r.cells)) for r in table.rows),
        total=total,
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


def points_side_table(plan: Plan, elec: Electrical) -> SideTable | None:
    """Точки: строка → точки с этими номерами."""
    table = points_table(plan, elec)
    if table is None:
        return None
    keys = [tuple(f"point:{p}" for p in r.point_ids) for r in point_rows(plan, elec)]
    return from_table(table, keys)


def lighting_side_table(plan: Plan, elec: Electrical) -> SideTable | None:
    """Выключатели: строка → выключатель и свет, который он включает."""
    built = switch_table(plan, elec)
    if built is None:
        return None
    table, notes = built
    keys = []
    strips = {s.id for s in elec.led_strips}
    for r in switch_rows(plan, elec):
        keys.append(tuple(f"led_strip:{i}" if i in strips else f"point:{i}" for i in r.point_ids))
    return from_table(table, keys, notes)


def group_side_table(
    plan: Plan,
    elec: Electrical,
    wiring: Wiring | None = None,
    panel: BoardPanel | None = None,
    extra: Sequence[str] = (),
) -> SideTable | None:
    """«Группы»: строка → точки, кабели, линии и коробки группы. В узкой панели — без
    колонки «Точек» (она на листе): иначе не помещается мощность."""
    built = groups_table(plan, elec, wiring, panel)
    if built is None:
        return None
    table, notes = built
    runs = wiring.runs if wiring is not None else ()
    boxes = wiring.boxes if wiring is not None else ()
    keys = [
        tuple(
            [f"point:{p}" for p in r.point_ids]
            + [f"cable:{c}" for c in r.cable_ids]
            + [f"wire:{w.id}" for w in runs if w.group == r.group]
            + [f"box:{b.id}" for b in boxes if b.group == r.group]
        )
        for r in group_rows(plan, elec)
    ]
    side = from_table(table, keys, [*notes, *extra])
    points = side.columns.index(groups_text("points", plan.language))
    return drop_column(side, points)


def estimate_side_table(
    wiring: Wiring,
    elec: Electrical,
    language: Language,
    prices: PriceList | None,
    panel: BoardPanel | None = None,
) -> SideTable:
    """Смета (с прайсом) или ведомость объёмов — для вкладки «Смета» просмотра (ключ estimate
    страницы проводки); на печати — тот же расчёт на листе проводки (stages.wiring_panels)."""
    est = build_estimate(wiring, elec, prices or PriceList(), language, panel)
    notes = [estimate_text("note_panel", language)] if panel is not None else []
    if prices is not None:
        date = f" ({prices.date})" if prices.date else ""
        notes.insert(0, estimate_text("sheet_prices", language, f=PRICES_FILE, date=date))
        if est.unpriced:
            notes.append(estimate_text("unpriced", language, n=est.unpriced, f=PRICES_FILE))
    table = from_table(estimate_table(est, language, priced=prices is not None), notes=notes)
    hints = {ln.name: ln.hint for ln in est.lines if ln.hint}
    rows = tuple(
        replace(r, hint=hints.get(r.cells[1])) if len(r.cells) > 1 else r for r in table.rows
    )
    return replace(table, rows=rows)


def side_tables(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical | None,
    wiring: Wiring | None,
    prices: PriceList | None = None,
    quantities: Wiring | None = None,
) -> dict[str, list[SideTable]]:
    """Таблицы боковой панели по теме листа (plan / electrical / wiring / panel …) и смета
    (estimate) — на страницу проводки отдельным ключом, для вкладки «Смета» просмотра."""
    lang = plan.language
    out = {"plan": [room_table(plan, contours)]}
    if elec is not None:
        tables = legend_tables(elec, lang)
        points = points_side_table(plan, elec)
        if points is not None:
            tables.insert(0, points)
        out["electrical"] = tables
        lighting = lighting_side_table(plan, elec)
        out["lighting"] = [lighting] if lighting is not None else []
        if points is not None:
            out["points"] = [points]
        panel = build_panel(plan, elec)
        if wiring is not None:
            groups = group_side_table(plan, elec, wiring, panel, wiring_notes(wiring, lang))
            out["wiring"] = [groups] if groups is not None else []
            out["estimate"] = [estimate_side_table(quantities or wiring, elec, lang, prices, panel)]
        if panel is not None:
            out["panel"] = panel_tables(panel, elec, lang)
    return out


def panel_tables(panel: BoardPanel, elec: Electrical, language: Language) -> list[SideTable]:
    """Лист «Щит»: аппараты с нагрузкой и слабыми местами (строка → аппарат) и роспись
    потребителей по группам. Закупка аппаратов — в смете (вкладка «Смета»)."""
    colors = group_colors(elec)
    table = devices_table(panel, language, colors)
    keys = [(d.key,) for d in panel.devices]
    # Назначение в панели не помещается — оно в карточке аппарата по клику на строку
    out = [drop_column(from_table(table, keys, panel_notes(panel, language)), 1)]
    rows = []
    for g in panel.groups:
        c = color_of(g.group, colors)
        color = f"#{c:06x}" if c is not None else None
        head = (g.group, g.purpose, "", f"{g.power:g}")
        rows.append(SideRow(head, (f"device:{g.group}",), section=True, color=color))
        for ld in g.loads:
            title = ld.title + (f" ×{ld.count}" if ld.count > 1 else "")
            power = f"{ld.power:g}" + (ASSUMED if ld.assumed else "")
            rows.append(SideRow(("", title, ld.room, power), (f"device:{g.group}",)))
    out.append(
        SideTable(
            text("consumers", language),
            (
                text("group", language),
                text("consumer", language),
                text("room", language),
                text("watts", language),
            ),
            ("center", "left", "left", "center"),
            tuple(rows),
            ("", text("total", language), "", f"{panel.installed:g}"),
        )
    )
    return out
