"""Ведомости этапов на лист: «Точки», «Группы», смета. Строки
считают расчёты (electrical/), здесь — колонки, ширины по метрикам шрифта и таблица листа.
"""

from __future__ import annotations

from collections.abc import Sequence

from floorplan_engine.drawing.layers import TEXT_DIM_MM, text_width
from floorplan_engine.drawing.tables import CELL_PAD, TEXT_GAP, Column, Mark, Table, name_width
from floorplan_engine.electrical.estimate import Estimate, format_number
from floorplan_engine.electrical.estimate import text as estimate_text
from floorplan_engine.electrical.groups import ASSUMED, GroupRow, group_colors, group_rows
from floorplan_engine.electrical.groups import text as groups_text
from floorplan_engine.electrical.panel import BoardPanel
from floorplan_engine.electrical.panel_text import kw
from floorplan_engine.electrical.point_numbers import point_rows
from floorplan_engine.electrical.point_numbers import text as points_text
from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.model.texts import Language

POINTS_ROW_H = 5.5  # строки «Точек» плотнее обычных: точек много
POINTS_HEADER_H = 8.0


def _numbers_width(texts: Sequence[str]) -> float:
    """Колонка номеров — по самому длинному списку, не уже 10 мм."""
    return max(10.0, max(text_width(t, TEXT_DIM_MM) for t in texts) + 2 * CELL_PAD + TEXT_GAP)


def points_table(plan: Plan, elec: Electrical) -> Table | None:
    """Таблица «Точки» на лист электрики; точек нет — None."""
    lang = plan.language
    rows = point_rows(plan, elec)
    if not rows:
        return None
    columns = (
        Column(points_text("numbers", lang), _numbers_width([r.numbers for r in rows]), "left"),
        Column(points_text("point", lang), name_width([r.name for r in rows]), "left"),
        Column(points_text("height", lang), 22.0),
        Column(points_text("count", lang), 10.0),
    )
    cells = tuple((r.numbers, r.name, r.height, str(r.count)) for r in rows)
    return Table(
        points_text("title", lang), columns, cells, row_h=POINTS_ROW_H, header_h=POINTS_HEADER_H
    )


def groups_table(
    plan: Plan,
    elec: Electrical,
    wiring: Wiring | None = None,
    panel: BoardPanel | None = None,
) -> tuple[Table, list[str]] | None:
    """«Группы» — одна строка на группу: назначение, автомат и мощность (с листа «Щит»),
    кабель и длина без запаса (из проводки), точек; итог — длина, точки, мощность. Без
    проводки или щита — их колонок нет. Групп нет — None."""
    lang = plan.language
    rows = group_rows(plan, elec)
    if not rows:
        return None
    purposes = [r.purpose + (ASSUMED if r.assumed else "") for r in rows]
    lengths: dict[str, float] = {}
    marks: dict[str, str] = {}
    for run in wiring.runs if wiring is not None else ():
        lengths[run.group] = lengths.get(run.group, 0.0) + run.length_mm
        marks[run.group] = run.mark + (ASSUMED if run.mark_assumed else "")
    devices = {
        d.group: d.label + (ASSUMED if d.assumed else "")
        for d in (panel.devices if panel is not None else ())
        if d.group is not None
    }
    powers = {g.group: g for g in (panel.groups if panel is not None else ())}

    def breaker(r: GroupRow) -> str:
        return devices.get(r.group) or r.breaker

    def power(r: GroupRow) -> str:
        g = powers.get(r.group)
        if g is None:
            return ""
        return kw(g.power) + (ASSUMED if any(ld.assumed for ld in g.loads) else "")

    with_breaker = panel is not None or any(r.breaker for r in rows)
    columns = [
        Column(groups_text("group", lang), 20.0),
        Column(groups_text("purpose", lang), name_width(purposes), "left"),
    ]
    if with_breaker:
        columns.append(Column(groups_text("breaker", lang), 24.0))
    columns.append(Column(groups_text("cable", lang), 18.0))
    if wiring is not None:
        columns.append(Column(groups_text("length", lang), 20.0))
    columns.append(Column(groups_text("points", lang), 14.0))
    if panel is not None:
        columns.append(Column(groups_text("power", lang), 16.0))
    colors = group_colors(elec)
    cells = tuple(
        (
            Mark(r.group, colors[r.group]),
            p,
            *((breaker(r),) if with_breaker else ()),
            marks.get(r.group) or r.cable,
            *((format_number(lengths.get(r.group, 0.0) / 1000, 1),) if wiring is not None else ()),
            str(r.points),
            *((power(r),) if panel is not None else ()),
        )
        for r, p in zip(rows, purposes, strict=True)
    )
    total = (
        groups_text("total", lang),
        "",
        *(("",) if with_breaker else ()),
        "",
        *(
            (format_number(sum(r.length_mm for r in wiring.runs) / 1000, 1),)
            if wiring is not None
            else ()
        ),
        str(sum(r.points for r in rows)),
        *((kw(panel.installed),) if panel is not None else ()),
    )
    notes = [groups_text("note", lang)] if any(r.assumed for r in rows) else []
    flagged = [*marks.values(), *devices.values(), *(power(r) for r in rows)]
    if any(x.endswith(ASSUMED) for x in flagged):
        notes.append(groups_text("note_assumed", lang))
    return Table(groups_text("title", lang), tuple(columns), cells, total=total), notes


ESTIMATE_ROW_H = 5.5  # мм листа: строка сметы на листе — плотнее обычной таблицы (8)
ESTIMATE_HEADER_H = 8.0


def estimate_table(est: Estimate, language: Language, priced: bool) -> Table:
    """Смета на лист: разделы, их итоги и «Всего»; без прайса — ведомость объёмов
    (только количества)."""

    def t(key: str, **values: object) -> str:
        return estimate_text(key, language, **values)

    names = [ln.name for ln in est.lines]
    names += [t("section_total", s=t(sec).lower()) for sec in ("material", "work")]
    # Ширина наименований — по метрикам шрифта: колонка таблиц на листе шириной со штамп
    name_w = max(text_width(n, TEXT_DIM_MM) for n in names) + 2 * CELL_PAD + TEXT_GAP
    columns = [
        Column(t("col_no"), 8.0),
        Column(t("col_name"), name_w, "left"),
        Column(t("col_unit"), 10.0),
        Column(t("col_qty"), 14.0),
    ]
    if priced:
        columns += [
            Column(t("col_price", c=est.currency), 17.0),
            Column(t("col_sum", c=est.currency), 21.0),
        ]
    rows: list[tuple[str, ...]] = []
    for section in ("material", "work"):
        lines = [ln for ln in est.lines if ln.section == section]
        if not lines:
            continue
        rows.append(("", t(section), "", "", *(("", "") if priced else ())))
        for k, ln in enumerate(lines, 1):
            qty = format_number(ln.qty, 1).removesuffix(",0")
            money = (
                (
                    format_number(ln.price) if ln.price is not None else "—",
                    format_number(ln.total) if ln.total is not None else "—",
                )
                if priced
                else ()
            )
            rows.append((str(k), ln.name, ln.unit, qty, *money))
        if priced:
            subtotal = t("section_total", s=t(section).lower())
            rows.append(("", subtotal, "", "", "", format_number(est.subtotal(section))))
    total = ("", t("total"), "", "", "", format_number(est.total)) if priced else None
    title = t("sheet_title") if priced else t("sheet_volumes")
    return Table(
        title, tuple(columns), tuple(rows), total, row_h=ESTIMATE_ROW_H, header_h=ESTIMATE_HEADER_H
    )
