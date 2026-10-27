"""Группы щита отдельной таблицей: QF, назначение, кабель, точки, автомат. На чертеже
и в остальных таблицах у групп только «QF4» — подробности здесь, чтобы не мусорить.

Назначение и автомат берутся из electrical.yaml (groups) — только из источника. Нет
назначения — оно составляется по точкам группы («Розетки — Спальня») и помечается «*»
как допущение; автомат не составляется никогда.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from shtroba.draw_electrical import group_colors, group_key
from shtroba.schema import Electrical, ElectricalPoint, Plan, PointType
from shtroba.tables import Column, Mark, Table, name_width
from shtroba.texts import Language

ASSUMED = "*"

TEXT: dict[str, dict[str, str]] = {
    "title": {"ru": "Группы щита", "uk": "Групи щита"},
    "group": {"ru": "Группа", "uk": "Група"},
    "purpose": {"ru": "Назначение", "uk": "Призначення"},
    "cable": {"ru": "Кабель", "uk": "Кабель"},
    "points": {"ru": "Точек", "uk": "Точок"},
    "breaker": {"ru": "Аппарат", "uk": "Апарат"},
    "light": {"ru": "Освещение", "uk": "Освітлення"},
    "sockets": {"ru": "Розетки", "uk": "Розетки"},
    "socket": {"ru": "Розетка", "uk": "Розетка"},
    "outlets": {"ru": "Выводы", "uk": "Виводи"},
    "outlet": {"ru": "Вывод", "uk": "Вивід"},
    "low": {"ru": "Слаботочка", "uk": "Слабкий струм"},
    "switches": {"ru": "Выключатели", "uk": "Вимикачі"},
    "note": {
        "ru": "* — назначение составлено по точкам группы; уточните",
        "uk": "* — призначення складено за точками групи; уточніть",
    },
}

LIGHT = frozenset(
    {
        PointType.LIGHT,
        PointType.DOWNLIGHT,
        PointType.PENDANT,
        PointType.SCONCE,
        PointType.LED_OUTPUT,
    }
)
SWITCHES = frozenset({PointType.SWITCH, PointType.PASS_SWITCH})
LOW = frozenset({PointType.DATA, PointType.TV})


def text(key: str, language: Language) -> str:
    return TEXT[key][language]


@dataclass(frozen=True)
class GroupRow:
    group: str
    purpose: str
    assumed: bool  # назначение составлено по точкам, а не взято из модели
    cable: str
    points: int
    breaker: str  # автомат и УЗО из модели; нет — пусто
    point_ids: tuple[str, ...]
    cable_ids: tuple[str, ...]


def composed_purpose(
    points: Sequence[ElectricalPoint], rooms: dict[str, str], language: Language
) -> str:
    """Назначение по точкам группы: виды точек (выключатели — к освещению) и помещения.
    Одна розетка или вывод с пометкой — по пометке: «Розетка: духовка»."""
    types = {p.type for p in points}
    where = ", ".join(dict.fromkeys(rooms.get(p.room, p.room) for p in points))
    single = {PointType.SOCKET: "socket", PointType.OUTLET: "outlet"}
    if len(points) == 1 and points[0].note and points[0].type in single:
        what = f"{text(single[points[0].type], language)}: {points[0].note}"
        return f"{what} — {where}"
    kinds = []
    if types & LIGHT:
        kinds.append(text("light", language))
    if PointType.SOCKET in types:
        kinds.append(text("sockets", language))
    outlets = [p for p in points if p.type is PointType.OUTLET]
    if outlets:
        kinds.append(text("outlet" if len(outlets) == 1 else "outlets", language))
    if types & LOW:
        kinds.append(text("low", language))
    if not kinds and types & SWITCHES:
        kinds.append(text("switches", language))
    what = ", ".join(k if n == 0 else k[0].lower() + k[1:] for n, k in enumerate(kinds))
    return f"{what} — {where}" if where else what


def group_rows(plan: Plan, elec: Electrical) -> list[GroupRow]:
    """Строки по группам в порядке номеров; группа — у точки или у кабеля."""
    lang = plan.language
    rooms = {r.id: r.name for r in plan.rooms}
    names = {p.group for p in elec.points if p.group} | {c.group for c in elec.cables if c.group}
    out = []
    for group in sorted(names, key=group_key):
        points = [p for p in elec.points if p.group == group]
        cables = [c for c in elec.cables if c.group == group]
        info = elec.groups.get(group)
        purpose = info.name if info is not None and info.name else None
        device = ", ".join(x for x in (info.breaker, info.rcd) if x) if info is not None else ""
        out.append(
            GroupRow(
                group,
                purpose or composed_purpose(points, rooms, lang),
                purpose is None,
                ", ".join(sorted({c.cable for c in cables})),
                sum(p.count for p in points),
                device,
                tuple(p.id for p in points),
                tuple(c.id for c in cables),
            )
        )
    return out


def groups_table(plan: Plan, elec: Electrical) -> tuple[Table, list[str]] | None:
    """Таблица групп на лист электрики и примечание о допущениях; групп нет — None.
    Колонка аппарата — только если он есть в модели хоть у одной группы."""
    lang = plan.language
    rows = group_rows(plan, elec)
    if not rows:
        return None
    purposes = [r.purpose + (ASSUMED if r.assumed else "") for r in rows]
    with_device = any(r.breaker for r in rows)
    columns = [
        Column(text("group", lang), 20.0),
        Column(text("purpose", lang), name_width(purposes), "left"),
        Column(text("cable", lang), 18.0),
        Column(text("points", lang), 14.0),
    ]
    if with_device:
        columns.append(Column(text("breaker", lang), 26.0))
    colors = group_colors(elec)
    cells = tuple(
        (
            Mark(r.group, colors[r.group]),
            p,
            r.cable,
            str(r.points),
            *((r.breaker,) if with_device else ()),
        )
        for r, p in zip(rows, purposes, strict=True)
    )
    notes = [text("note", lang)] if any(r.assumed for r in rows) else []
    return Table(text("title", lang), tuple(columns), cells), notes
