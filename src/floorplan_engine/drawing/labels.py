"""Размещение подписей на листе без наложений (отзыв 2026-10-28: подписи электрики налезали
на стены, двери, символы и друг на друга).

Подпись — блок строк. Кандидаты — места вокруг символа: у точки на стене — со стороны
помещения, со сдвигом вдоль стены и от неё; у потолочной — по восьми сторонам; дальше —
дальний поиск по 16 направлениям. У каждого места штраф: задевает уже поставленную подпись,
символ, дверь или LED-ленту, ложится на стену (за наружными стенами — свободно: в тесном
помещении подпись выносится за контур квартиры); выноска пересекает подпись или символ;
плюс расстояние от символа. Берётся место с наименьшим штрафом; подпись дальше
`Metrics.leader_min` от символа — с выноской.

Геометрия — мм модели; размеры «на листе» пересчитывает вызывающий (`scale.sheet`).
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from shapely import STRtree
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from floorplan_engine.model.geometry import Vec

# Штрафы: подпись на подписи хуже всего, затем символ и дверь, затем выход на стену
HIT_LABEL = 10_000.0
HIT_SYMBOL = 5_000.0
HIT_ZONE = 3_000.0  # дверь, LED-лента
HIT_FRAME = 6_000.0  # подпись выходит за рамку плана: раздует вид и сменит масштаб листа
HIT_LEADER = 2_000.0  # выноска пересекает подпись или чужой символ
HIT_ROOM = 1_500.0  # подпись заходит в чужое помещение: монтажник ищет её не там
PAD = 0.3  # запас вокруг подписи, доля высоты строки: соседние не встают впритык
ON_WALL = 2_500.0  # подпись задевает стену
ON_WALL_AREA = 4_000.0  # и ещё × доля площади блока на стенах
# Расстояние — в шагах перебора (мм листа), чтобы не зависеть от масштаба
ALONG_COST = 1.0  # за шаг сдвига вдоль стены
AWAY_COST = 1.5  # за шаг от стены (дальше от символа — хуже читается связь)
FAR_COST = 2.0  # за шаг в дальнем поиске (с выноской)
LEADER_COST = 20.0  # выноска сама по себе


class Align(Enum):
    """Выравнивание строк в блоке: по левому краю, по правому, по центру."""

    LEFT = "left"
    RIGHT = "right"
    CENTER = "center"


@dataclass(frozen=True)
class Placed:
    """Поставленная подпись: строки (центр каждой строки по высоте), выравнивание,
    габарит блока и выноска (от символа к блоку) или None."""

    lines: list[tuple[str, Vec]]
    align: Align
    rect: tuple[float, float, float, float]
    leader: tuple[Vec, Vec] | None


@dataclass(frozen=True)
class Metrics:
    """Размеры текста в мм модели: высота строки, шаг строк, зазор от символа,
    шаг перебора мест и сколько шагов можно уйти рядом с символом (reach) и в дальнем поиске
    с выноской (far); выноска — если подпись дальше leader_min."""

    line_h: float
    step: float
    gap: float
    probe: float
    reach: int
    far: int
    leader_min: float


class LabelPlacer:
    """Ставит подписи по очереди; каждая поставленная — препятствие для следующих.

    walls — силуэт стен (подпись на них не ложится);
    symbols — габариты символов (ни подпись, ни выноска их не задевают); zones — куда подпись
    не ставится, а выноска пересекать может: открывание дверей, LED-ленты у стен; frame —
    рамка, за которую подпись не выходит (габарит плана с полосой); rooms — помещения по id:
    подпись не заходит в чужое (за контуром квартиры — можно)."""

    def __init__(
        self,
        walls: BaseGeometry,
        symbols: Sequence[BaseGeometry],
        zones: Sequence[BaseGeometry],
        metrics: Metrics,
        frame: BaseGeometry | None = None,
        rooms: Mapping[str, BaseGeometry] | None = None,
    ) -> None:
        self.walls = walls
        self.frame = frame
        self.room_ids = list(rooms or {})
        self.rooms = [(rooms or {})[r] for r in self.room_ids]
        self.room_tree = STRtree(self.rooms)
        self.symbols = list(symbols)
        self.symbol_tree = STRtree(self.symbols)
        self.zones = list(zones)
        self.zone_tree = STRtree(self.zones)
        self.taken: list[BaseGeometry] = []
        self.m = metrics

    def place(
        self,
        lines: Sequence[str],
        widths: Sequence[float],
        pos: Vec,
        inward: Vec | None,
        depth: float,
        own: BaseGeometry | None = None,
        room: str | None = None,
    ) -> Placed:
        """Подпись символа в pos: inward — в помещение (None — потолок), depth — насколько
        символ выступает от стены (у потолочного — радиус); own — габарит своих символов,
        он подписи не мешает; room — помещение символа."""
        w = max(widths)
        h = self.m.step * (len(lines) - 1) + self.m.line_h
        best: tuple[float, tuple[float, float, float, float], Align] | None = None
        for rect, align, dist in self._candidates(w, h, pos, inward, depth):
            if best is not None and dist >= best[0]:
                continue  # штраф не отрицательный — дальнее место уже не лучше
            cost = dist + self._penalty(rect, own, room)
            leader = self._leader(rect, pos, inward, depth)
            if leader is not None:
                cost += self._leader_penalty(leader, own)
            if best is None or cost < best[0]:
                best = (cost, rect, align)
                if cost == 0.0:
                    break
        assert best is not None
        _, rect, align = best
        pad = self.m.line_h * PAD
        self.taken.append(box(*rect).buffer(pad, join_style="mitre"))
        leader = self._leader(rect, pos, inward, depth)
        if leader is not None:
            self.taken.append(
                LineString([leader[0].as_tuple(), leader[1].as_tuple()]).buffer(pad / 2)
            )
        return Placed(self._lines(lines, rect, align), align, rect, leader)

    # --- кандидаты -----------------------------------------------------------

    def _candidates(
        self, w: float, h: float, pos: Vec, inward: Vec | None, depth: float
    ) -> Iterator[tuple[tuple[float, float, float, float], Align, float]]:
        """Места по возрастанию расстояния: рядом с символом, затем дальний поиск."""
        m = self.m
        base = depth + m.gap
        if inward is None:
            for away in range(m.reach + 1):
                for i, v in enumerate(_DIRS[:8]):
                    rect, align = _beside(pos + v * (base + away * m.probe), v, w, h)
                    yield rect, align, away * AWAY_COST + i * 0.01
        else:
            n, u = inward, inward.left()  # в помещение и вдоль стены
            shifts = [0] + [s for k in range(1, m.reach + 1) for s in (k, -k)]
            for away in range(m.reach + 1):
                for s in shifts:
                    c = pos + n * (base + away * m.probe) + u * (s * m.probe)
                    rect, align = _beside(c, n, w, h)
                    yield rect, align, abs(s) * ALONG_COST + away * AWAY_COST
        # Рядом места нет — дальше по 16 направлениям, с выноской
        for away in range(m.reach + 1, m.far + 1, 2):
            for v in _DIRS:  # и за стену — наружу квартиры: стену штрафует _penalty
                rect, align = _beside(pos + v * (base + away * m.probe), v, w, h)
                yield rect, align, away * FAR_COST + LEADER_COST

    # --- штраф ---------------------------------------------------------------

    def _penalty(
        self, rect: tuple[float, float, float, float], own: BaseGeometry | None, room: str | None
    ) -> float:
        b = box(*rect)
        cost = 0.0
        if room is not None and any(
            self.room_ids[j] != room and b.intersection(self.rooms[j]).area > 0
            for j in self.room_tree.query(b)
        ):
            cost += HIT_ROOM
        if any(b.intersection(t).area > 0 for t in self.taken):
            cost += HIT_LABEL
        for j in self.symbol_tree.query(b):
            g = self.symbols[j]
            if own is not None and g.within(own.buffer(1e-6)):
                continue
            if b.intersection(g).area > 0:
                cost += HIT_SYMBOL
                break
        if any(b.intersection(self.zones[j]).area > 0 for j in self.zone_tree.query(b)):
            cost += HIT_ZONE
        if self.frame is not None and not b.within(self.frame):
            cost += HIT_FRAME
        if not self.walls.is_empty:
            on = b.intersection(self.walls).area / b.area
            if on > 0:
                cost += ON_WALL + ON_WALL_AREA * on
        return cost

    def _leader_penalty(self, leader: tuple[Vec, Vec], own: BaseGeometry | None) -> float:
        line = LineString([leader[0].as_tuple(), leader[1].as_tuple()])
        if any(line.intersects(t) for t in self.taken):
            return HIT_LEADER
        for j in self.symbol_tree.query(line):
            g = self.symbols[j]
            if (own is None or not g.within(own.buffer(1e-6))) and line.intersects(g):
                return HIT_LEADER
        return 0.0

    # --- результат -----------------------------------------------------------

    def _lines(
        self, lines: Sequence[str], rect: tuple[float, float, float, float], align: Align
    ) -> list[tuple[str, Vec]]:
        x0, _, x1, y1 = rect
        x = {Align.LEFT: x0, Align.RIGHT: x1, Align.CENTER: (x0 + x1) / 2}[align]
        top = y1 - self.m.line_h / 2
        return [(t, Vec(x, top - k * self.m.step)) for k, t in enumerate(lines)]

    def _leader(
        self, rect: tuple[float, float, float, float], pos: Vec, inward: Vec | None, depth: float
    ) -> tuple[Vec, Vec] | None:
        tip = pos if inward is None else pos + inward * depth
        b, p = box(*rect), Point(tip.x, tip.y)
        if b.distance(p) <= depth + self.m.leader_min:
            return None
        near, _ = nearest_points(b, p)
        return (tip, Vec(near.x, near.y))


_DIRS = [
    Vec(math.cos(a), math.sin(a))
    for a in [0, math.pi, -math.pi / 2, math.pi / 2]
    + [-math.pi / 4, -3 * math.pi / 4, math.pi / 4, 3 * math.pi / 4]
    + [math.pi * (2 * k + 1) / 8 for k in range(8)]
]  # стороны, диагонали, промежуточные


def _beside(c: Vec, n: Vec, w: float, h: float) -> tuple[tuple[float, float, float, float], Align]:
    """Блок w × h, прижатый к точке c со стороны n: справа — по левому краю, слева — по
    правому, сверху и снизу — по центру."""
    if abs(n.x) > abs(n.y) + 1e-9:
        if n.x > 0:
            return (c.x, c.y - h / 2, c.x + w, c.y + h / 2), Align.LEFT
        return (c.x - w, c.y - h / 2, c.x, c.y + h / 2), Align.RIGHT
    if abs(n.y) > abs(n.x) + 1e-9:
        if n.y > 0:
            return (c.x - w / 2, c.y, c.x + w / 2, c.y + h), Align.CENTER
        return (c.x - w / 2, c.y - h, c.x + w / 2, c.y), Align.CENTER
    # Диагональ: угол блока — в точке c
    x0 = c.x if n.x > 0 else c.x - w
    y0 = c.y if n.y > 0 else c.y - h
    return (x0, y0, x0 + w, y0 + h), Align.LEFT if n.x > 0 else Align.RIGHT


def door_swing(hinge: Vec, closed: Vec, normal: Vec, width: float) -> BaseGeometry:
    """Зона открывания двери: четверть круга радиуса width у петли, со стороны normal."""
    quad = Polygon(
        [
            (hinge.x, hinge.y),
            (closed.x, closed.y),
            (closed.x + normal.x * width, closed.y + normal.y * width),
            (hinge.x + normal.x * width, hinge.y + normal.y * width),
        ]
    )
    return Point(hinge.x, hinge.y).buffer(width, 32).intersection(quad)
