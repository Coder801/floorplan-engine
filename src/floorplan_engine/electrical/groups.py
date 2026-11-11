"""Panel groups as a separate table: QF, purpose, cable, points, breaker. On the drawing and in
the other tables a group is just "QF4"; details live here to keep the rest clean.

Purpose and breaker come from electrical.yaml (groups), only from the source. Without a
purpose it is built from the group's points ("Розетки — Спальня") and marked "*" as an
assumption; a breaker is never made up.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from floorplan_engine.model.schema import Electrical, ElectricalPoint, Plan, PointType
from floorplan_engine.model.texts import Language
from floorplan_engine.model.zones import point_places

ASSUMED = "*"
DISTINCT_NOTES = 2  # notes that tell apart groups with the same purpose built from points

TEXT: dict[str, dict[str, str]] = {
    "title": {"ru": "Группы", "uk": "Групи"},
    "group": {"ru": "Группа", "uk": "Група"},
    "purpose": {"ru": "Назначение", "uk": "Призначення"},
    "cable": {"ru": "Кабель", "uk": "Кабель"},
    "points": {"ru": "Точек", "uk": "Точок"},
    "breaker": {"ru": "Автомат", "uk": "Автомат"},
    "phase": {"ru": "Фаза", "uk": "Фаза"},
    "length": {"ru": "Длина, м", "uk": "Довжина, м"},
    "power": {"ru": "P, кВт", "uk": "P, кВт"},
    "total": {"ru": "Итого", "uk": "Разом"},
    "light": {"ru": "Освещение", "uk": "Освітлення"},
    "sockets": {"ru": "Розетки", "uk": "Розетки"},
    "socket": {"ru": "Розетка", "uk": "Розетка"},
    "outlets": {"ru": "Выводы", "uk": "Виводи"},
    "outlet": {"ru": "Вывод", "uk": "Вивід"},
    "low": {"ru": "Связь", "uk": "Зв'язок"},
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
    assumed: bool  # purpose built from points, not taken from the model
    cable: str
    points: int
    breaker: str  # breaker and RCD from the model; empty if absent
    point_ids: tuple[str, ...]
    cable_ids: tuple[str, ...]


def composed_purpose(
    points: Sequence[ElectricalPoint], places: Mapping[str, str], language: Language
) -> str:
    """Purpose from the group's points: point kinds (switches count as lighting) and places
    (point id → zone or room name, model/zones.py; a point not in it takes its room id).
    A single socket or output with a note uses the note: "Розетка: духовка". The place is where
    the consumers are: a switch by the door of another room does not add it (the bathroom
    light switched from the hall is "Освітлення — Санвузол")."""
    types = {p.type for p in points}
    fed = [p for p in points if p.type not in SWITCHES] or points
    where = ", ".join(dict.fromkeys(places.get(p.id, p.room) for p in fed))
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


def tell_apart(items: Sequence[tuple[str, bool, Sequence[ElectricalPoint]]]) -> list[str]:
    """Purposes (purpose, built from points, points) where groups built from points read the
    same: two socket groups in one kitchen-living room with a hall. Those get the notes of their
    points at the end, "Розетки — Кухня (холодильник, мікрохвильова…)"; purposes from the model
    stay as they are."""
    same = Counter(purpose for purpose, built, _ in items if built)
    out = []
    for purpose, built, points in items:
        notes = list(dict.fromkeys(re.split(r"[,;(]", p.note)[0].strip() for p in points if p.note))
        if not built or same[purpose] < 2 or not notes:
            out.append(purpose)
            continue
        more = "…" if len(notes) > DISTINCT_NOTES else ""
        out.append(f"{purpose} ({', '.join(notes[:DISTINCT_NOTES])}{more})")
    return out


def group_rows(plan: Plan, elec: Electrical) -> list[GroupRow]:
    """Rows by group in number order; the group comes from the point or the cable."""
    lang = plan.language
    places = point_places(plan, elec.points)
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
                purpose or composed_purpose(points, places, lang),
                purpose is None,
                ", ".join(sorted({c.cable for c in cables})),
                sum(p.count for p in points),
                device,
                tuple(p.id for p in points),
                tuple(c.id for c in cables),
            )
        )
    by_id = {p.id: p for p in elec.points}
    told = tell_apart([(r.purpose, r.assumed, [by_id[i] for i in r.point_ids]) for r in out])
    return [replace(r, purpose=t) for r, t in zip(out, told, strict=True)]


def group_key(group: str) -> tuple[str, int, int]:
    """QF2 before QF10, line QF1.2 right after QF1: sort by the numbers in the group name."""
    m = re.match(r"^(\D*)(\d+)(?:\.(\d+))?", group)
    return (m.group(1), int(m.group(2)), int(m.group(3) or 1)) if m else (group, 0, 0)
