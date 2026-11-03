"""Cable routing on the plan: only inside rooms and through door openings.

The plan is split into a grid with step STEP. Cells inside rooms and in door openings are
free (at least CLEARANCE from walls), walls and windows are blocked. The path is the
shortest on the grid with a TURN_COST penalty per turn, so a route goes in straight runs at
90°. The path is computed once from a source (panel, box) to all its targets at once.

Any angle (any_angle: economy, docs/wiring-variants.md): the search goes in eight directions
without a turn penalty, then the path is pulled tight (pull): corners are cut where a straight
segment lies fully in the free area at least CLEARANCE from walls. The approach to a wall
point is as usual, perpendicular to the wall. This is only for ceiling and floor: on walls a
route is always vertical (chases in chases.py).
"""

from __future__ import annotations

import heapq
import itertools
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.model.geometry import RoomGeometry, Vec
from floorplan_engine.model.schema import Opening, OpeningType

STEP = 100.0  # mm: grid step
CLEARANCE = 150.0  # mm: clearance from walls (rule 2026-10-24), except the approach to a point
# on a wall and the pass through an opening
TURN_COST = 400.0  # mm: turn penalty
DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))
DIAGONALS = ((1, 1), (-1, 1), (-1, -1), (1, -1))
# Eight directions around the circle: neighbours differ by 45° (sewer uses search45)
DIRS8 = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
BEND_COST = TURN_COST / 2  # mm: penalty for a 45° bend


def free_area(geoms: Sequence[RoomGeometry]) -> BaseGeometry:
    """Rooms and openings of doors and open passages (not windows)."""
    parts: list[BaseGeometry] = [Polygon([v.as_tuple() for v in g.contour.vertices]) for g in geoms]
    for g in geoms:
        for op in g.room.openings:
            if op.type is not OpeningType.WINDOW:
                parts.append(opening_strip(g, op))
    return shapely.unary_union([shapely.make_valid(p) for p in parts])


def opening_strip(g: RoomGeometry, op: Opening) -> Polygon:
    """Opening on the plan: opening width, through the whole wall thickness outward from the
    room.
    """
    seg = g.contour.segment(op.wall)
    a, b = seg.point_at(op.offset), seg.point_at(op.offset + op.width)
    out = seg.outward * seg.thickness
    return Polygon([a.as_tuple(), b.as_tuple(), (b + out).as_tuple(), (a + out).as_tuple()])


def room_area(g: RoomGeometry) -> BaseGeometry:
    return shapely.make_valid(Polygon([v.as_tuple() for v in g.contour.vertices]))


@dataclass
class Grid:
    """Grid of free cells inside the area."""

    x0: float
    y0: float
    nx: int
    ny: int
    free: list[bool]
    inner: BaseGeometry | None = None  # area at least CLEARANCE from walls, for pull
    penalty: dict[int, float] | None = None  # extra cost to enter a cell, mm (plumbing)
    mult: list[float] | None = None  # cost per mm of a step into the cell (sewer: cheaper by walls)
    tag: list[int] | None = None  # cell kind for pruning in the search (sewer, network)

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
        # Slightly wider than the band itself: a segment along cell edges must not go "through the
        # wall" by rounding
        shapely.prepare(near := inner.buffer(1.0))
        return cls(minx + STEP / 2, miny + STEP / 2, nx, ny, [bool(v) for v in mask], near)

    def free_points(self) -> list[Vec]:
        """Centres of free cells: spots inside the area at least CLEARANCE from walls."""
        return [self.center(k) for k, ok in enumerate(self.free) if ok]

    def center(self, idx: int) -> Vec:
        iy, ix = divmod(idx, self.nx)
        return Vec(self.x0 + ix * STEP, self.y0 + iy * STEP)

    def nearest_free(self, p: Vec) -> int:
        """Free cell nearest to the point."""
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

    def search_any(self, start: int) -> tuple[dict[int, int], dict[int, float]]:
        """Dijkstra in eight directions with no turn penalty (any_angle): the state is a cell
        (direction 0), as in search, so path and cost are shared. Diagonal steps only if both
        neighbouring cells are free: wall corners are not cut."""
        dist: dict[int, float] = {start * 4: 0.0}
        prev: dict[int, int] = {start * 4: -1}
        heap: list[tuple[float, int]] = [(0.0, start * 4)]
        diagonal = STEP * math.sqrt(2)
        while heap:
            cost, state = heapq.heappop(heap)
            if cost > dist.get(state, float("inf")):
                continue
            iy, ix = divmod(state // 4, self.nx)
            for dx, dy in (*DIRS, *DIAGONALS):
                jx, jy = ix + dx, iy + dy
                if not (0 <= jx < self.nx and 0 <= jy < self.ny):
                    continue
                if not self.free[jy * self.nx + jx]:
                    continue
                side_a, side_b = self.free[iy * self.nx + jx], self.free[jy * self.nx + ix]
                if dx and dy and not (side_a and side_b):
                    continue
                ns = (jy * self.nx + jx) * 4
                c = cost + (diagonal if dx and dy else STEP)
                if c < dist.get(ns, float("inf")):
                    dist[ns] = c
                    prev[ns] = state
                    heapq.heappush(heap, (c, ns))
        return prev, dist

    def pull(self, cells: Sequence[Vec]) -> list[Vec]:
        """Pull the cell path tight: from each vertex go to the farthest one that a straight segment
        can reach without leaving the band at least CLEARANCE from walls."""
        if self.inner is None or len(cells) <= 2:
            return list(cells)
        out = [cells[0]]
        i = 0
        while i < len(cells) - 1:
            j = len(cells) - 1
            while j > i + 1:
                seg = shapely.LineString([cells[i].as_tuple(), cells[j].as_tuple()])
                if self.inner.covers(seg):
                    break
                j -= 1
            out.append(cells[j])
            i = j
        return out

    def search(self, start: int) -> tuple[dict[int, int], dict[int, float]]:
        """Dijkstra over states (cell, direction): state parents and costs."""
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
                if self.penalty is not None:
                    c += self.penalty.get(nxt, 0.0)
                ns = nxt * 4 + nd
                if c < dist.get(ns, float("inf")):
                    dist[ns] = c
                    prev[ns] = state
                    heapq.heappush(heap, (c, ns))
        return prev, dist

    def search45(
        self,
        start: int,
        bend: float = BEND_COST,
        prune: Callable[[int, float], bool] | None = None,
        start_len: float = 0.0,
    ) -> tuple[dict[int, int], dict[int, float]]:
        """Dijkstra over states (cell, one of the eight directions DIRS8): per step the direction
        changes by at most 45° (a 45° bend, penalty bend); a 90° turn is two bends with a diagonal
        step between. Diagonal steps only if both neighbouring cells are free. The state is
        cell · 8 + direction (path(..., ndirs=8)).
        A step costs length × the cell's mult (1 without mult) plus penalty. prune(cell, length)
        makes a cell unavailable at that geometric path length from the start (start_len is what
        was already travelled to the start cell): sewer pipe that no longer fits in the screed
        there."""
        dist: dict[int, float] = {}
        prev: dict[int, int] = {}
        glen: dict[int, float] = {}
        heap: list[tuple[float, int]] = []
        for d in range(8):
            s = start * 8 + d
            dist[s] = 0.0
            prev[s] = -1
            glen[s] = start_len
            heapq.heappush(heap, (0.0, s))
        diagonal = STEP * math.sqrt(2)
        while heap:
            cost, state = heapq.heappop(heap)
            if cost > dist.get(state, float("inf")):
                continue
            cell, d = divmod(state, 8)
            iy, ix = divmod(cell, self.nx)
            for nd in ((d + 7) % 8, d, (d + 1) % 8):
                dx, dy = DIRS8[nd]
                jx, jy = ix + dx, iy + dy
                if not (0 <= jx < self.nx and 0 <= jy < self.ny):
                    continue
                nxt = jy * self.nx + jx
                if not self.free[nxt]:
                    continue
                if (
                    dx
                    and dy
                    and not (self.free[iy * self.nx + jx] and self.free[jy * self.nx + ix])
                ):
                    continue
                step = diagonal if dx and dy else STEP
                length = glen[state] + step
                if prune is not None and prune(nxt, length):
                    continue
                k = self.mult[nxt] if self.mult is not None else 1.0
                c = cost + step * k + (bend if nd != d else 0.0)
                if self.penalty is not None:
                    c += self.penalty.get(nxt, 0.0)
                ns = nxt * 8 + nd
                if c < dist.get(ns, float("inf")):
                    dist[ns] = c
                    prev[ns] = state
                    glen[ns] = length
                    heapq.heappush(heap, (c, ns))
        return prev, dist

    def path(
        self, prev: dict[int, int], dist: dict[int, float], target: int, ndirs: int = 4
    ) -> list[Vec]:
        states = [target * ndirs + d for d in range(ndirs) if target * ndirs + d in prev]
        if not states:
            raise ValueError("цель недостижима: помещение отрезано стенами без проёмов")
        state = min(states, key=lambda s: dist[s])
        cells = []
        while state != -1:
            cells.append(state // ndirs)
            state = prev[state]
        return [self.center(c) for c in reversed(cells)]


def _join(node: Vec, cell: Vec, vertical_wall: bool) -> list[Vec]:
    """From the connection point to the cell centre in two pieces at 90°: away from the wall
    first.
    """
    if abs(node.x - cell.x) < 1e-6 or abs(node.y - cell.y) < 1e-6:
        return [node]
    corner = Vec(cell.x, node.y) if vertical_wall else Vec(node.x, cell.y)
    return [node, corner]


def simplify(path: Sequence[Vec]) -> list[Vec]:
    """No duplicates and no collinear points."""
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
    """Move the end of an orthogonal route to point p keeping right angles: the neighbouring vertex
    shifts across the first piece; a single-piece route gets a bend."""
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
    """Manual route with its ends at the source and target nodes (if they moved)."""
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
    """Route end: connection point and wall orientation (None for ceiling)."""

    node: Vec
    vertical_wall: bool


class Router:
    """Routes from one source to many targets in a given area. any_angle allows any angle
    (economy): the shortest path is pulled tight instead of running at 90°."""

    def __init__(self, area: BaseGeometry, source: End, any_angle: bool = False) -> None:
        self.grid = Grid.of(area)
        self.source = source
        self.any_angle = any_angle
        self.start = self.grid.nearest_free(source.node)
        search = self.grid.search_any if any_angle else self.grid.search
        self.prev, self.dist = search(self.start)

    def cost(self, node: Vec) -> float:
        """Route cost to the point (with turns); infinity if unreachable."""
        cell = self.grid.nearest_free(node)
        costs = [self.dist[s] for s in range(cell * 4, cell * 4 + 4) if s in self.dist]
        return min(costs, default=float("inf"))

    def route(self, target: End) -> list[Vec]:
        cell = self.grid.nearest_free(target.node)
        middle = self.grid.path(self.prev, self.dist, cell)
        if self.any_angle:
            middle = self.grid.pull(middle)
        head = _join(self.source.node, middle[0], self.source.vertical_wall)
        tail = list(reversed(_join(target.node, middle[-1], target.vertical_wall)))
        return simplify([*head, *middle, *tail])


def length(path: Sequence[Vec]) -> float:
    """Route length on the plan; pieces at any angle (the same for right angles)."""
    return sum(math.hypot(b.x - a.x, b.y - a.y) for a, b in itertools.pairwise(path))


def is_ortho(path: Sequence[Vec], tol: float = 0.5) -> bool:
    """All pieces run along the axes (standard and premium)."""
    return all(abs(a.x - b.x) <= tol or abs(a.y - b.y) <= tol for a, b in itertools.pairwise(path))
