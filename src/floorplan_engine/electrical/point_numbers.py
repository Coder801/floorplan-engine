"""Point numbers on the electrical sheet and the "Points" table (decision 2026-10-28).

On the plan a symbol carries only a number ("7", or "7–9" for neighbouring points on one
wall); kind, height and note are in the table in the margin. Identical points (kind,
height, note) share one row with a list of numbers: the table is shorter and the plan
does not repeat text.

Numbering goes by room in room.yaml order; inside a room, wall points by wall walk and
offset, then ceiling points top to bottom, left to right. The number is not stored in the
model: add a point and the numbers after it shift.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from floorplan_engine.model.schema import Electrical, ElectricalPoint, Plan, PointType
from floorplan_engine.model.texts import Language

TEXT: dict[str, dict[str, str]] = {
    "title": {"ru": "Точки", "uk": "Точки"},
    "numbers": {"ru": "№", "uk": "№"},
    "point": {"ru": "Точка", "uk": "Точка"},
    "height": {"ru": "Высота, мм", "uk": "Висота, мм"},
    "count": {"ru": "Шт.", "uk": "Шт."},
    "ceiling": {"ru": "потолок", "uk": "стеля"},
    "posts": {"ru": "{n}-постовая", "uk": "{n}-постова"},
}

NAMES: dict[str, dict[str, str]] = {
    "socket": {"ru": "Розетка", "uk": "Розетка"},
    "switch": {"ru": "Выключатель", "uk": "Вимикач"},
    "switch2": {"ru": "Выключатель 2-клавишный", "uk": "Вимикач 2-клавішний"},
    "pass_switch": {"ru": "Выключатель проходной", "uk": "Вимикач прохідний"},
    "light": {"ru": "Светильник", "uk": "Світильник"},
    "downlight": {"ru": "Светильник точечный", "uk": "Світильник точковий"},
    "pendant": {"ru": "Светильник подвесной", "uk": "Світильник підвісний"},
    "sconce": {"ru": "Бра", "uk": "Бра"},
    "data": {"ru": "Розетка интернет", "uk": "Розетка інтернет"},
    "tv": {"ru": "Розетка TV", "uk": "Розетка TV"},
    "led_output": {"ru": "Вывод под подсветку", "uk": "Вивід для підсвітки"},
    "outlet": {"ru": "Вывод кабеля", "uk": "Вивід кабелю"},
}


def text(key: str, language: Language, **kw: object) -> str:
    return TEXT[key][language].format(**kw)


def point_name(p: ElectricalPoint, language: Language) -> str:
    """Point kind label such as "Розетка", "Вимикач 2-клавішний: коридор"; a block gets its number
    of posts."""
    key = "switch2" if p.type is PointType.SWITCH and p.keys == 2 else p.type.value
    name = NAMES[key][language]
    if p.count > 1 and p.type in (PointType.SOCKET, PointType.DATA, PointType.TV):
        name = f"{name} {text('posts', language, n=p.count)}"
    return f"{name}: {p.note}" if p.note else name


def number_points(plan: Plan, elec: Electrical) -> dict[str, int]:
    """Number of each point, from 1."""
    room_order = {r.id: k for k, r in enumerate(plan.rooms)}
    wall_order = {(r.id, w.id): k for r in plan.rooms for k, w in enumerate(r.walls)}

    def key(p: ElectricalPoint) -> tuple[float, ...]:
        room = float(room_order.get(p.room, len(room_order)))
        if p.ceiling is not None:
            return (room, 1.0, -p.ceiling[1], p.ceiling[0])
        wall = float(wall_order.get((p.room, p.wall or ""), 0))
        return (room, 0.0, wall, p.offset or 0.0)

    ordered = sorted(elec.points, key=key)
    return {p.id: k for k, p in enumerate(ordered, 1)}


def ranges(numbers: Sequence[int]) -> str:
    """1, 2, 3, 7 → "1–3, 7"; two in a row are comma-separated: "4, 5"."""
    nums = sorted(set(numbers))
    out: list[str] = []
    k = 0
    while k < len(nums):
        j = k
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        if j - k >= 2:
            out.append(f"{nums[k]}–{nums[j]}")
        else:
            out.extend(str(n) for n in nums[k : j + 1])
        k = j + 1
    return ", ".join(out)


@dataclass(frozen=True)
class PointRow:
    numbers: str
    name: str
    height: str
    count: int  # posts (devices) over all points of the row
    point_ids: tuple[str, ...]


def point_rows(plan: Plan, elec: Electrical) -> list[PointRow]:
    """Table rows: identical points (kind, height, note) together, ordered by first number."""
    lang = plan.language
    numbers = number_points(plan, elec)
    groups: dict[tuple[str, str], list[ElectricalPoint]] = {}
    for p in sorted(elec.points, key=lambda p: numbers[p.id]):
        height = text("ceiling", lang) if p.ceiling is not None else f"{p.height or 0:g}"
        groups.setdefault((point_name(p, lang), height), []).append(p)
    return [
        PointRow(
            ranges([numbers[p.id] for p in pts]),
            name,
            height,
            sum(p.count for p in pts),
            tuple(p.id for p in pts),
        )
        for (name, height), pts in groups.items()
    ]
