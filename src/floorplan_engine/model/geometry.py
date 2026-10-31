"""Геометрия: обход контура, невязка, площадь, внешний контур стен, привязка к стенам;
помещение с контуром и внешними углами (RoomGeometry) — общая основа плана, трасс и развёрток.

Система координат чертежа: X вправо, Y вверх, мм. Обход стен — по часовой стрелке,
поэтому помещение лежит справа от направления стены, а толщина стены откладывается влево.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from floorplan_engine.model.schema import Plan, Room

# Высоты проёмов, которых нет в room.yaml, — допущения (3D-сцена, развёртки)
DOOR_TOP_MM = 2100.0
WINDOW_SILL_MM = 900.0
WINDOW_HEIGHT_MM = 1400.0

CLOSURE_TOLERANCE_MM = 10.0
ANGLE_TOLERANCE_DEG = 0.01
_EPS = 1e-9


@dataclass(frozen=True)
class Vec:
    x: float
    y: float

    def __add__(self, other: Vec) -> Vec:
        return Vec(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vec) -> Vec:
        return Vec(self.x - other.x, self.y - other.y)

    def __mul__(self, k: float) -> Vec:
        return Vec(self.x * k, self.y * k)

    def dot(self, other: Vec) -> float:
        return self.x * other.x + self.y * other.y

    def cross(self, other: Vec) -> float:
        return self.x * other.y - self.y * other.x

    def length(self) -> float:
        return math.hypot(self.x, self.y)

    def left(self) -> Vec:
        """Нормаль влево (поворот на +90°)."""
        return Vec(-self.y, self.x)

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)


@dataclass(frozen=True)
class WallSegment:
    index: int  # номер в обходе
    id: str
    start: Vec
    end: Vec
    direction: Vec  # единичный вектор
    length: float
    thickness: float
    bearing: bool

    @property
    def outward(self) -> Vec:
        """Единичная нормаль наружу помещения."""
        return self.direction.left()

    @property
    def inward(self) -> Vec:
        return self.outward * -1.0

    @property
    def angle_deg(self) -> float:
        return math.degrees(math.atan2(self.direction.y, self.direction.x))

    def point_at(self, offset: float) -> Vec:
        """Точка на внутренней грани стены на расстоянии offset от её начала."""
        return self.start + self.direction * offset


@dataclass(frozen=True)
class ClosureSuspect:
    wall: str  # id стены
    current_length: float
    fixed_length: float | None  # длина, при которой контур замкнётся (если её достаточно)


@dataclass(frozen=True)
class Contour:
    segments: tuple[WallSegment, ...]
    gap: Vec  # конец последней стены минус origin
    angle_sum_error: float  # отклонение суммы поворотов от 360°, градусы

    def segment(self, wall_id: str) -> WallSegment:
        """Стена по id; id проверяются валидацией до геометрии."""
        return next(s for s in self.segments if s.id == wall_id)

    @property
    def vertices(self) -> list[Vec]:
        """Вершины внутреннего контура (начала стен)."""
        return [s.start for s in self.segments]

    @property
    def closure_error(self) -> float:
        return self.gap.length()

    def is_closed(self, tolerance: float = CLOSURE_TOLERANCE_MM) -> bool:
        return self.closure_error <= tolerance and abs(self.angle_sum_error) <= ANGLE_TOLERANCE_DEG

    @property
    def area_mm2(self) -> float:
        return abs(signed_area(self.vertices))

    @property
    def area_m2(self) -> float:
        return self.area_mm2 / 1_000_000

    @property
    def perimeter(self) -> float:
        return sum(s.length for s in self.segments)


def _unit(angle_deg: float) -> Vec:
    rad = math.radians(angle_deg)
    # округление убирает шум вида 6e-17 у осевых направлений
    return Vec(round(math.cos(rad), 12), round(math.sin(rad), 12))


def trace_contour(room: Room, default_thickness: float) -> Contour:
    """Строит внутренний контур комнаты обходом стен по часовой стрелке."""
    heading = room.start_angle
    pos = Vec(*room.origin)
    segments: list[WallSegment] = []
    turn_total = 0.0
    for i, wall in enumerate(room.walls):
        direction = _unit(heading)
        end = pos + direction * wall.length
        segments.append(
            WallSegment(
                index=i,
                id=wall.id,
                start=pos,
                end=end,
                direction=direction,
                length=wall.length,
                thickness=wall.thickness if wall.thickness is not None else default_thickness,
                bearing=wall.bearing,
            )
        )
        # Внутренний угол 90° — поворот направо на 90°, 270° — налево на 90°
        right_turn = 180.0 - wall.turn
        turn_total += right_turn
        heading -= right_turn
        pos = end
    gap = pos - Vec(*room.origin)
    return Contour(tuple(segments), gap, turn_total - 360.0)


def expected_angle_sum(n_walls: int) -> float:
    """Сумма внутренних углов многоугольника."""
    return (n_walls - 2) * 180.0


def closure_suspects(
    contour: Contour, tolerance: float = CLOSURE_TOLERANCE_MM
) -> list[ClosureSuspect]:
    """Стены, исправлением длины которых можно замкнуть контур.

    Сначала — стены, параллельные вектору невязки (их длину можно поправить точно).
    Если таких нет — стены, у которых есть составляющая вдоль невязки.
    """
    gap = contour.gap
    if gap.length() <= _EPS:
        return []
    exact: list[ClosureSuspect] = []
    partial: list[ClosureSuspect] = []
    for seg in contour.segments:
        along = gap.dot(seg.direction)
        across = abs(gap.cross(seg.direction))
        if across <= tolerance and abs(along) > _EPS:
            new_length = seg.length - along
            if new_length > 0:
                exact.append(ClosureSuspect(seg.id, seg.length, round(new_length, 1)))
        elif abs(along) > tolerance:
            partial.append(ClosureSuspect(seg.id, seg.length, None))
    return exact or partial


def signed_area(points: Sequence[Vec]) -> float:
    """Площадь по формуле Гаусса: > 0 для обхода против часовой стрелки."""
    total = 0.0
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        total += a.cross(b)
    return total / 2.0


def _segments_intersect(p1: Vec, p2: Vec, q1: Vec, q2: Vec) -> bool:
    """Собственное пересечение отрезков (касание концами не считается)."""
    d1 = (p2 - p1).cross(q1 - p1)
    d2 = (p2 - p1).cross(q2 - p1)
    d3 = (q2 - q1).cross(p1 - q1)
    d4 = (q2 - q1).cross(p2 - q1)
    return d1 * d2 < -_EPS and d3 * d4 < -_EPS


def self_intersections(contour: Contour) -> list[tuple[str, str]]:
    """Пары несмежных стен (их id), которые пересекаются."""
    segs = contour.segments
    n = len(segs)
    result: list[tuple[str, str]] = []
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue  # смежные через замыкание
            if _segments_intersect(segs[i].start, segs[i].end, segs[j].start, segs[j].end):
                result.append((segs[i].id, segs[j].id))
    return result


def point_in_polygon(point: Vec, polygon: Sequence[Vec]) -> bool:
    """Луч вправо; точка на границе считается внутри."""
    inside = False
    n = len(polygon)
    for i in range(n):
        a, b = polygon[i], polygon[(i + 1) % n]
        if abs((b - a).cross(point - a)) <= 1e-6 and (
            min(a.x, b.x) - 1e-6 <= point.x <= max(a.x, b.x) + 1e-6
            and min(a.y, b.y) - 1e-6 <= point.y <= max(a.y, b.y) + 1e-6
        ):
            return True
        if (a.y > point.y) != (b.y > point.y):
            x_cross = a.x + (point.y - a.y) * (b.x - a.x) / (b.y - a.y)
            if point.x < x_cross:
                inside = not inside
    return inside


def _line_intersection(p: Vec, d: Vec, q: Vec, e: Vec) -> Vec | None:
    denom = d.cross(e)
    if abs(denom) < _EPS:
        return None
    t = (q - p).cross(e) / denom
    return p + d * t


def outer_corners(contour: Contour) -> list[Vec]:
    """Внешние углы стен: пересечения смещённых наружу граней соседних стен.

    corners[i] — внешняя точка в начале стены i (стык со стеной i-1).
    """
    segs = contour.segments
    n = len(segs)
    corners: list[Vec] = []
    for i in range(n):
        prev, cur = segs[i - 1], segs[i]
        p = prev.start + prev.outward * prev.thickness
        q = cur.start + cur.outward * cur.thickness
        hit = _line_intersection(p, prev.direction, q, cur.direction)
        # Коллинеарные стены (turn 180): стык по нормали текущей стены
        corners.append(hit if hit is not None else q)
    return corners


@dataclass(frozen=True)
class RoomGeometry:
    room: Room
    contour: Contour
    corners: list[Vec]  # внешние углы стен

    def outer_point(self, seg: WallSegment, offset: float) -> Vec:
        return seg.point_at(offset) + seg.outward * seg.thickness

    def outer_start(self, seg: WallSegment) -> Vec:
        return self.corners[seg.index]

    def outer_end(self, seg: WallSegment) -> Vec:
        return self.corners[(seg.index + 1) % len(self.corners)]


def room_geometries(plan: Plan, contours: dict[str, Contour]) -> list[RoomGeometry]:
    return [
        RoomGeometry(room, contours[room.id], outer_corners(contours[room.id]))
        for room in plan.rooms
    ]
