"""Где стоит распаечная коробка: на потолке — в центре своих точек, не ближе
routing.CLEARANCE к стенам (place_ceiling_box); у трасс по полу — на стене (шаг BOX_STEP,
не ближе BOX_CLEARANCE к углам, place_box). Охват веток по трассе (branch_reach),
типоразмер по числу линий (box_size), деление точек по зонам (split_points), перенос
коробки по правке из просмотра (moved_anchor)."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from shapely.geometry import Point
from shapely.ops import nearest_points

from floorplan_engine.electrical.anchors import Anchor
from floorplan_engine.electrical.routing import (
    CLEARANCE,
    End,
    Grid,
    Router,
    room_area,
)
from floorplan_engine.model.geometry import RoomGeometry, Vec, WallSegment
from floorplan_engine.model.scale import sheet

BOX_STEP = 100.0  # мм: шаг перебора мест коробки вдоль стены
BOX_CLEARANCE = 150.0  # мм: от угла и от проёма до коробки
BOX_SPACING = 200.0  # мм: коробки разных групп в помещении не ближе этого
BOX_SIZE_MM = 2.5  # сторона квадрата коробки, мм листа
# Типоразмеры коробок и сколько линий (вводов) в них заводить — по нижней границе
# практики (решение 2026-10-25); 190×140 — только в крайнем случае
# Ключ — для прайса (junction_box.100x100), название — для сметы и подсказок
BOX_SIZES: tuple[tuple[str, int], ...] = (("80", 3), ("100x100", 6), ("150x110", 8))
BOX_LARGE = ("190x140", 10)
BOX_ORDER = (*(k for k, _ in BOX_SIZES), BOX_LARGE[0])
BOX_TITLES = {"80": "Ø80", "100x100": "100×100", "150x110": "150×110", "190x140": "190×140"}
BOX_BRANCHES = BOX_SIZES[-1][1] - 1  # веток на коробку: одна линия — питающая от щита
# Места на потолке, где ветки длиннее самых коротких не больше чем на эту долю, считаются
# равными — из них коробка встаёт ближе к центру своих точек
CENTER_SLACK = 0.1


def _manhattan(a: Vec, b: Vec) -> float:
    return abs(a.x - b.x) + abs(a.y - b.y)


def anchor_end(a: Anchor) -> End:
    return End(a.node, a.wall_is_vertical)


def _box_candidates(g: RoomGeometry, depth: float) -> list[Anchor]:
    out: list[Anchor] = []
    for seg in g.contour.segments:
        spans = [(o.offset, o.offset + o.width) for o in g.room.openings if o.wall == seg.id]
        offset = BOX_CLEARANCE
        while offset <= seg.length - BOX_CLEARANCE:
            if all(not (a - BOX_CLEARANCE < offset < b + BOX_CLEARANCE) for a, b in spans):
                out.append(Anchor(seg.point_at(offset), seg.inward, seg.direction, depth))
            offset += BOX_STEP
    return out


# Стоимость веток из места коробки до её точек: сумма путей по трассе в обход стен
Reach = Callable[[Vec], float]


def branch_reach(g: RoomGeometry, targets: Sequence[Anchor], any_angle: bool = False) -> Reach:
    """Сумма путей от места до точек по трассе внутри помещения (с поворотами), а не по
    прямой: коробка не встанет за перегородку от своих точек."""
    area = room_area(g)
    routers = [Router(area, anchor_end(t), any_angle) for t in targets]
    return lambda p: sum(r.cost(p) for r in routers)


def place_box(g: RoomGeometry, board: Router, reach: Reach, taken: Sequence[Vec]) -> Anchor | None:
    """Место на стене, где путь от щита плюс ветки до точек наименьшие."""
    best: tuple[float, Anchor] | None = None
    for cand in _box_candidates(g, sheet(BOX_SIZE_MM)):
        if any(_manhattan(cand.node, t) < BOX_SPACING for t in taken):
            continue
        cost = board.cost(cand.node) + reach(cand.node)
        if best is None or cost < best[0] - 1e-6:
            best = (cost, cand)
    return None if best is None else best[1]


def box_size(lines: int) -> str:
    """Коробка под число линий (питающая + ветки) — по нижней границе вводов; 190×140 —
    только если линий больше, чем у 150×110 (на практике — не бывает: группа делится)."""
    return next((name for name, cap in BOX_SIZES if lines <= cap), BOX_LARGE[0])


def split_points(points: Sequence[Vec], cap: int) -> list[list[int]]:
    """Точки по зонам не больше cap в каждой: деление пополам (с учётом числа зон) по более
    протяжённой оси — соседние точки попадают в одну коробку."""
    idx = list(range(len(points)))

    def split(part: list[int]) -> list[list[int]]:
        if len(part) <= cap:
            return [part]
        k = math.ceil(len(part) / cap)
        xs = [points[i].x for i in part]
        ys = [points[i].y for i in part]
        axis = 0 if max(xs) - min(xs) >= max(ys) - min(ys) else 1
        part = sorted(part, key=lambda i: (points[i].x, points[i].y)[axis])
        cut = round(len(part) * (k // 2) / k)
        return split(part[:cut]) + split(part[cut:])

    return split(idx)


def place_ceiling_box(
    g: RoomGeometry, reach: Reach, targets: Sequence[Anchor], taken: Sequence[Vec], depth: float
) -> Anchor | None:
    """Коробка на потолке: место внутри помещения не ближе CLEARANCE к стенам в центре своих
    точек. Из мест, где ветки до точек по трассе не длиннее самых коротких на CENTER_SLACK, —
    ближайшее к середине точек: путь от щита место не выбирает (одна питающая линия не
    тянет коробку к стене со стороны щита)."""
    spots = [
        (reach(p), p)
        for p in Grid.of(room_area(g)).free_points()
        if all(_manhattan(p, t) >= BOX_SPACING for t in taken)
    ]
    if not spots:
        return None
    limit = min(c for c, _ in spots) * (1 + CENTER_SLACK) + 1e-6
    mid = Vec(
        sum(t.node.x for t in targets) / len(targets),
        sum(t.node.y for t in targets) / len(targets),
    )
    _, best = min(
        ((c, p) for c, p in spots if c <= limit), key=lambda s: ((s[1] - mid).length(), s[0])
    )
    return Anchor(best, None, None, depth)


def box_wall(g: RoomGeometry, anchor: Anchor) -> WallSegment | None:
    """Стена, на которой стоит коробка (символ); на потолке — None."""
    if anchor.wall_dir is None:
        return None
    for seg in g.contour.segments:
        v = anchor.pos - seg.start
        along = v.dot(seg.direction)
        if (
            seg.direction.dot(anchor.wall_dir) > 0.99
            and abs(seg.direction.cross(v)) < 1.0
            and -1.0 <= along <= seg.length + 1.0
        ):
            return seg
    return None


def moved_anchor(g: RoomGeometry, anchor: Anchor, at: Vec) -> Anchor | None:
    """Новое место коробки: на стене — проекция на её стену, не ближе BOX_CLEARANCE к углам;
    на потолке — точка внутри помещения, а ближе CLEARANCE к стенам — ближайшее место на этом
    расстоянии. None — места нет."""
    if anchor.inward is None:
        area = room_area(g)
        pt = Point(at.x, at.y)
        if not area.contains(pt):
            return None
        inner = area.buffer(-CLEARANCE, join_style="mitre")
        if not inner.is_empty and not inner.contains(pt):
            near = nearest_points(inner, pt)[0]
            at = Vec(near.x, near.y)
        return Anchor(at, None, None, anchor.depth)
    seg = box_wall(g, anchor)
    if seg is None or seg.length < 2 * BOX_CLEARANCE:
        return None
    offset = min(
        max((at - seg.start).dot(seg.direction), BOX_CLEARANCE), seg.length - BOX_CLEARANCE
    )
    return Anchor(seg.point_at(offset), seg.inward, seg.direction, anchor.depth)
