"""Трассировка кабеля по плану: только внутри помещений и через дверные проёмы.

План разбивается на сетку с шагом STEP. Свободны ячейки внутри помещений и в проёмах
дверей (не ближе CLEARANCE к стенам), стены и окна закрыты. Путь — кратчайший по сетке
со штрафом TURN_COST за каждый поворот: так трасса идёт прямыми участками под 90°.
Путь считается один раз от источника (щит, коробка) сразу до всех его целей.
"""

from __future__ import annotations

import heapq
import itertools
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.draw_plan import RoomGeometry
from floorplan_engine.geometry import Vec
from floorplan_engine.schema import Opening, OpeningType

STEP = 100.0  # мм — шаг сетки
CLEARANCE = 150.0  # мм — трасса не ближе к стенам (правило 2026-10-24); кроме подхода к точке
# на стене и прохода в проёме
TURN_COST = 400.0  # мм — штраф за поворот
DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))


def free_area(geoms: Sequence[RoomGeometry]) -> BaseGeometry:
    """Помещения и проёмы дверей и открытых проёмов (окна — нет)."""
    parts: list[BaseGeometry] = [Polygon([v.as_tuple() for v in g.contour.vertices]) for g in geoms]
    for g in geoms:
        for op in g.room.openings:
            if op.type is not OpeningType.WINDOW:
                parts.append(opening_strip(g, op))
    return shapely.unary_union([shapely.make_valid(p) for p in parts])


def opening_strip(g: RoomGeometry, op: Opening) -> Polygon:
    """Проём на плане: по ширине проёма, на всю толщину стены наружу от помещения."""
    seg = g.contour.segment(op.wall)
    a, b = seg.point_at(op.offset), seg.point_at(op.offset + op.width)
    out = seg.outward * seg.thickness
    return Polygon([a.as_tuple(), b.as_tuple(), (b + out).as_tuple(), (a + out).as_tuple()])


def room_area(g: RoomGeometry) -> BaseGeometry:
    return shapely.make_valid(Polygon([v.as_tuple() for v in g.contour.vertices]))


@dataclass
class Grid:
    """Сетка свободных ячеек внутри области."""

    x0: float
    y0: float
    nx: int
    ny: int
    free: list[bool]

    @classmethod
    def of(cls, area: BaseGeometry) -> Grid:
        inner = area.buffer(-CLEARANCE, join_style="mitre")
        minx, miny, maxx, maxy = area.bounds
        nx = int((maxx - minx) // STEP) + 2
        ny = int((maxy - miny) // STEP) + 2
        xs = minx + STEP / 2 + np.arange(nx) * STEP
        ys = miny + STEP / 2 + np.arange(ny) * STEP
        gx, gy = np.meshgrid(xs, ys)  # [iy, ix]
        mask = shapely.contains_xy(inner, gx.ravel(), gy.ravel())
        return cls(minx + STEP / 2, miny + STEP / 2, nx, ny, [bool(v) for v in mask])

    def free_points(self) -> list[Vec]:
        """Центры свободных ячеек: места внутри области не ближе CLEARANCE к стенам."""
        return [self.center(k) for k, ok in enumerate(self.free) if ok]

    def center(self, idx: int) -> Vec:
        iy, ix = divmod(idx, self.nx)
        return Vec(self.x0 + ix * STEP, self.y0 + iy * STEP)

    def nearest_free(self, p: Vec) -> int:
        """Ближайшая к точке свободная ячейка."""
        best, best_d = -1, float("inf")
        cx = round((p.x - self.x0) / STEP)
        cy = round((p.y - self.y0) / STEP)
        for r in range(max(self.nx, self.ny)):
            for iy in range(cy - r, cy + r + 1):
                for ix in range(cx - r, cx + r + 1):
                    if max(abs(ix - cx), abs(iy - cy)) != r:
                        continue
                    if 0 <= ix < self.nx and 0 <= iy < self.ny and self.free[iy * self.nx + ix]:
                        c = self.center(iy * self.nx + ix)
                        d = abs(c.x - p.x) + abs(c.y - p.y)
                        if d < best_d:
                            best, best_d = iy * self.nx + ix, d
            if best >= 0:
                return best
        raise ValueError("на плане нет свободного места для трассы")

    def search(self, start: int) -> tuple[dict[int, int], dict[int, float]]:
        """Дейкстра по состояниям (ячейка, направление): предки и стоимость состояний."""
        dist: dict[int, float] = {}
        prev: dict[int, int] = {}
        heap: list[tuple[float, int]] = []
        for d in range(4):
            s = start * 4 + d
            dist[s] = 0.0
            prev[s] = -1
            heapq.heappush(heap, (0.0, s))
        while heap:
            cost, state = heapq.heappop(heap)
            if cost > dist.get(state, float("inf")):
                continue
            cell, d = divmod(state, 4)
            iy, ix = divmod(cell, self.nx)
            for nd, (dx, dy) in enumerate(DIRS):
                jx, jy = ix + dx, iy + dy
                if not (0 <= jx < self.nx and 0 <= jy < self.ny):
                    continue
                nxt = jy * self.nx + jx
                if not self.free[nxt]:
                    continue
                c = cost + STEP + (TURN_COST if nd != d else 0.0)
                ns = nxt * 4 + nd
                if c < dist.get(ns, float("inf")):
                    dist[ns] = c
                    prev[ns] = state
                    heapq.heappush(heap, (c, ns))
        return prev, dist

    def path(self, prev: dict[int, int], dist: dict[int, float], target: int) -> list[Vec]:
        states = [target * 4 + d for d in range(4) if target * 4 + d in prev]
        if not states:
            raise ValueError("цель недостижима: помещение отрезано стенами без проёмов")
        state = min(states, key=lambda s: dist[s])
        cells = []
        while state != -1:
            cells.append(state // 4)
            state = prev[state]
        return [self.center(c) for c in reversed(cells)]


def _join(node: Vec, cell: Vec, vertical_wall: bool) -> list[Vec]:
    """От точки подключения до центра ячейки — двумя участками под 90°: сначала от стены."""
    if abs(node.x - cell.x) < 1e-6 or abs(node.y - cell.y) < 1e-6:
        return [node]
    corner = Vec(cell.x, node.y) if vertical_wall else Vec(node.x, cell.y)
    return [node, corner]


def simplify(path: Sequence[Vec]) -> list[Vec]:
    """Без повторов и без точек на прямой."""
    out: list[Vec] = []
    for p in path:
        if out and abs(p.x - out[-1].x) < 1e-6 and abs(p.y - out[-1].y) < 1e-6:
            continue
        if len(out) >= 2:
            a, b = out[-2], out[-1]
            if (abs(a.x - b.x) < 1e-6 and abs(b.x - p.x) < 1e-6) or (
                abs(a.y - b.y) < 1e-6 and abs(b.y - p.y) < 1e-6
            ):
                out[-1] = p
                continue
        out.append(p)
    return out


def move_end(path: Sequence[Vec], at_start: bool, p: Vec) -> list[Vec]:
    """Конец ортогональной трассы — в точку p, углы остаются прямыми: соседняя вершина
    сдвигается поперёк первого участка; трасса из одного участка получает излом."""
    pts = list(path) if at_start else list(reversed(path))
    a, b = pts[0], pts[1]
    horizontal = abs(a.y - b.y) <= abs(a.x - b.x)
    if len(pts) >= 3:
        pts[0] = p
        pts[1] = Vec(b.x, p.y) if horizontal else Vec(p.x, b.y)
    else:
        pts = [p, Vec(b.x, p.y) if horizontal else Vec(p.x, b.y), b]
    out = simplify(pts)
    return out if at_start else list(reversed(out))


def fit_path(path: Sequence[Vec], start: Vec, end: Vec, tol: float = 0.5) -> list[Vec]:
    """Ручная трасса с концами в узлах источника и цели (если они сдвинулись)."""
    out = list(path)
    if abs(out[0].x - start.x) > tol or abs(out[0].y - start.y) > tol:
        out = move_end(out, True, start)
    else:
        out[0] = start
    if abs(out[-1].x - end.x) > tol or abs(out[-1].y - end.y) > tol:
        out = move_end(out, False, end)
    else:
        out[-1] = end
    return simplify(out)


@dataclass(frozen=True)
class End:
    """Конец трассы: точка подключения и ориентация стены (None — потолок)."""

    node: Vec
    vertical_wall: bool


class Router:
    """Трассы от одного источника до многих целей в заданной области."""

    def __init__(self, area: BaseGeometry, source: End) -> None:
        self.grid = Grid.of(area)
        self.source = source
        self.start = self.grid.nearest_free(source.node)
        self.prev, self.dist = self.grid.search(self.start)

    def cost(self, node: Vec) -> float:
        """Стоимость трассы до точки (с поворотами); недостижимо — бесконечность."""
        cell = self.grid.nearest_free(node)
        costs = [self.dist[s] for s in range(cell * 4, cell * 4 + 4) if s in self.dist]
        return min(costs, default=float("inf"))

    def route(self, target: End) -> list[Vec]:
        cell = self.grid.nearest_free(target.node)
        middle = self.grid.path(self.prev, self.dist, cell)
        head = _join(self.source.node, middle[0], self.source.vertical_wall)
        tail = list(reversed(_join(target.node, middle[-1], target.vertical_wall)))
        return simplify([*head, *middle, *tail])


def length(path: Sequence[Vec]) -> float:
    return sum(abs(b.x - a.x) + abs(b.y - a.y) for a, b in itertools.pairwise(path))
