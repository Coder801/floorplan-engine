"""Группы щита отдельной таблицей: QF, назначение, кабель, точки, автомат. На чертеже
и в остальных таблицах у групп только «QF4» — подробности здесь, чтобы не мусорить.

Назначение и автомат берутся из electrical.yaml (groups) — только из источника. Нет
назначения — оно составляется по точкам группы («Розетки — Спальня») и помечается «*»
как допущение; автомат не составляется никогда.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from floorplan_engine.model.schema import Electrical, ElectricalPoint, Plan, PointType
from floorplan_engine.model.texts import Language

ASSUMED = "*"

TEXT: dict[str, dict[str, str]] = {
    "title": {"ru": "Группы", "uk": "Групи"},
    "group": {"ru": "Группа", "uk": "Група"},
    "purpose": {"ru": "Назначение", "uk": "Призначення"},
    "cable": {"ru": "Кабель", "uk": "Кабель"},
    "points": {"ru": "Точек", "uk": "Точок"},
    "breaker": {"ru": "Автомат", "uk": "Автомат"},
    "length": {"ru": "Длина, м", "uk": "Довжина, м"},
    "power": {"ru": "P, кВт", "uk": "P, кВт"},
    "total": {"ru": "Итого", "uk": "Разом"},
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
    "note_assumed": {
        "ru": "* у автомата, кабеля и мощности — подобрано кодом (лист «Щит»), а не из проекта",
        "uk": "* в автомата, кабелю і потужності — підібрано кодом (аркуш «Щит»), а не з проєкту",
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


# Цвета групп — мягкие, RGB (true color в DXF), различимые между собой и читаемые тонкой
# линией на белом (решение 2026-10-25); серых нет: просмотр в тёмной теме перекрашивает серое
GROUP_PALETTE = (
    "#4e79a7",  # синий
    "#f28e2b",  # оранжевый
    "#59a14f",  # зелёный
    "#e15759",  # красный
    "#76b7b2",  # бирюзовый
    "#d4a72c",  # охра
    "#b07aa1",  # сиреневый
    "#e67f8a",  # розовый
    "#9c755f",  # коричневый
    "#5f9ed1",  # голубой
    "#8cbf5f",  # салатовый
    "#c9845c",  # терракота
    "#7f7fc9",  # лавандовый
    "#4fb0a0",  # морская волна
)


def group_key(group: str) -> tuple[str, int, int]:
    """QF2 раньше QF10, линия QF1.2 — сразу после QF1: сортировка по числам в имени группы."""
    m = re.match(r"^(\D*)(\d+)(?:\.(\d+))?", group)
    return (m.group(1), int(m.group(2)), int(m.group(3) or 1)) if m else (group, 0, 0)


def rgb(hex_color: str) -> int:
    """«#4e79a7» → число true color DXF (0xRRGGBB)."""
    return int(hex_color.lstrip("#"), 16)


def group_colors(elec: Electrical) -> dict[str, int]:
    """Свой цвет (true color, 0xRRGGBB) для каждой группы — по порядку номеров."""
    groups = sorted(
        {p.group for p in elec.points if p.group} | {c.group for c in elec.cables if c.group},
        key=group_key,
    )
    return {g: rgb(GROUP_PALETTE[k % len(GROUP_PALETTE)]) for k, g in enumerate(groups)}
