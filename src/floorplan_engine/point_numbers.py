"""Номера точек на листе электрики и таблица «Точки» (решение 2026-10-28).

На плане у символа — только номер («7», у соседних точек одной стены — «7–9»); вид, высота
и примечание — в таблице на полях. Одинаковые точки (вид, высота, примечание) — одной
строкой со списком номеров: так таблица короче, а на плане текст не повторяется.

Нумерация — по помещениям в порядке room.yaml; в помещении — точки на стенах по обходу
стен и отступу, затем потолочные сверху вниз, слева направо. Номер не хранится в модели:
добавили точку — номера после неё сдвинутся.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from floorplan_engine.layers import TEXT_DIM_MM, text_width
from floorplan_engine.schema import Electrical, ElectricalPoint, Plan, PointType
from floorplan_engine.tables import CELL_PAD, TEXT_GAP, Column, Table, name_width
from floorplan_engine.texts import Language

ROW_H = 5.5  # строки плотнее обычных: точек много
HEADER_H = 8.0

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
    """«Розетка», «Вимикач 2-клавішний: коридор»; у блока — число постов."""
    key = "switch2" if p.type is PointType.SWITCH and p.keys == 2 else p.type.value
    name = NAMES[key][language]
    if p.count > 1 and p.type in (PointType.SOCKET, PointType.DATA, PointType.TV):
        name = f"{name} {text('posts', language, n=p.count)}"
    return f"{name}: {p.note}" if p.note else name


def number_points(plan: Plan, elec: Electrical) -> dict[str, int]:
    """Номер каждой точки, с 1."""
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
    """1, 2, 3, 7 → «1–3, 7»; два подряд — через запятую: «4, 5»."""
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
    count: int  # постов (механизмов) по всем точкам строки
    point_ids: tuple[str, ...]


def point_rows(plan: Plan, elec: Electrical) -> list[PointRow]:
    """Строки таблицы: одинаковые точки (вид, высота, примечание) вместе, по первому номеру."""
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


def _width(texts: Sequence[str]) -> float:
    """Колонка номеров — по самому длинному списку, не уже 10 мм."""
    return max(10.0, max(text_width(t, TEXT_DIM_MM) for t in texts) + 2 * CELL_PAD + TEXT_GAP)


def points_table(plan: Plan, elec: Electrical) -> Table | None:
    """Таблица «Точки» на лист электрики; точек нет — None."""
    lang = plan.language
    rows = point_rows(plan, elec)
    if not rows:
        return None
    columns = (
        Column(text("numbers", lang), _width([r.numbers for r in rows]), "left"),
        Column(text("point", lang), name_width([r.name for r in rows]), "left"),
        Column(text("height", lang), 22.0),
        Column(text("count", lang), 10.0),
    )
    cells = tuple((r.numbers, r.name, r.height, str(r.count)) for r in rows)
    return Table(text("title", lang), columns, cells, row_h=ROW_H, header_h=HEADER_H)
