"""Cable routing on the plan: inside rooms, through door openings and, if the way round through
a door is long, through a wall that may be drilled.

The plan is split into a grid with step STEP. Cells inside rooms and in door openings are
free (at least CLEARANCE from walls), windows are blocked. The path is the shortest on the grid
with a TURN_COST penalty per turn, so a route goes in straight runs at 90°. The path is computed
once from a source (panel, box) to all its targets at once.

Walls (decision 2026-11-11): a wall between two rooms of the flat that is not load-bearing and no
thicker than WALL_DRILL_MAX (or explicitly `partition: true`) may be drilled (drillable_walls).
Its band plus CLEARANCE on each side is open, a pass across it costs about WALL_PASS_COST
whatever the thickness (spread over the cells across the band); running along a wall inside its
band costs several times the cable and is not worth it. Load-bearing walls, outer walls and thick
walls (shafts, pylons, boxes) are never crossed: a room behind one is reached only through an
opening.

Openings cost like a wall on the ceiling (decision 2026-11-23, ceiling_passes): a route on the
ceiling passes a door or an opening above it, through the same wall the estimate drills
(chases.wall_holes), so on the ceiling plane the strip of every door and opening whose top is
lower than the ceiling (below_ceiling; a door without a height is DOOR_TOP_MM) costs WALL_PASS_COST
too, as a drillable wall (less PASS_FAVOUR, half a grid step, so an exact tie goes through the
opening); a door and the opening of the neighbour at the same spot are one band (the cost is the
maximum per cell, not a sum). An opening up to the ceiling is free, and on the floor every
opening is free: there is no wall under a door. So a route takes the opening only when it is
shorter that way with the pass counted, otherwise it goes straight through a drillable wall.

A ready hole is free (decision 2026-11-23, holes): where a line of the build has already crossed a
band on the same plane and circuit (wiring_routes.route_runs routes lines one after another and
passes the crossings on), the cells of the band within WALL_HOLE_SHARE of that crossing cost a
residual per cell instead of the pass, so the next lines follow into the same hole, as the
estimate counts them (one hole for lines closer than WALL_HOLE_SHARE). The residual is
HOLE_CELL_COST for a hole made by a line of the same source (own) and twice that for any other
line's hole: it only decides ties, so that a route leaves the band at once instead of running
along it, and that cables of one box or flush box leave it together rather than split between two
holes at the same length.

Any angle (any_angle: economy, docs/wiring-variants.md): the search goes in eight directions
without a turn penalty, then the path is pulled tight (pull): corners are cut where a straight
segment lies fully in the free area at least CLEARANCE from walls. The approach to a wall
point is as usual, perpendicular to the wall. This is only for ceiling and floor: on walls a
route is always vertical (chases in chases.py).

Jog at the drop (decision 2026-11-18, slide_jog): the grid runs on cell centres, so a point off
them, or one whose line passes a wall end within CLEARANCE, got a short sideways step right at
its wall — a zigzag where the elevations round every turn with the cable's radius. The step is
slid back along the route to the farthest spot from which the route runs on the point's line,
and disappears if the whole piece is clear.

Low-voltage apart from power (decision 2026-11-13, apart_cells): an internet or TV cable keeps
APART from a power cable running the same way and crosses it at 90°. A step along a power piece
closer than APART costs APART_COST more, a step across it costs nothing extra, so the route goes
beside the power bundle and comes close only where there is no other way (a narrow corridor,
a socket block): the rule is a cost, not a ban. Within PANEL_FREE of the panel (decision
2026-11-18, calm) neither applies: all cables leave the panel together, so there the route goes
the short way, beside power or across it at any spot. Only for routes at right angles: at any
angle there is no "the same way".
"""

from __future__ import annotations

import heapq
import itertools
import math
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.electrical import trace
from floorplan_engine.model.geometry import (
    DOOR_TOP_MM,
    RoomGeometry,
    Vec,
    WallSegment,
    point_in_polygon,
)
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
WALL_DRILL_MAX = 300.0  # mm: thicker non-bearing walls (shafts, pylons, boxes) are not drilled
WALL_PASS_COST = 1000.0  # mm: one pass through a drillable wall weighs as this much cable
WALL_HOLE_SHARE = 300.0  # mm: lines crossing a wall closer than this share a hole (wall_holes)
# mm: an opening band costs this much less than a wall, half a grid step: at equal length a route
# takes the opening rather than a new hole in the wall; any longer way round still loses
PASS_FAVOUR = STEP / 2
# mm: a band cell at a ready hole of the same source; twice that at another line's hole. A
# tie-breaker only: the route leaves the band at once and follows the lines of its own source
HOLE_CELL_COST = 1.0
# A ready hole: the piece of a routed line across a band of a wall or an opening (crossings)
Crossing = tuple[Vec, Vec]
APART = 150.0  # mm: a low-voltage cable runs no closer than this beside a power cable
APART_COST = 3000.0  # mm: one grid step beside a power cable closer than APART weighs this much
PANEL_FREE = 300.0  # mm: around the panel a low-voltage cable need not keep APART (2026-11-18)
JOG_MAX = 2 * STEP  # mm: a sideways step at a route's end this short is slid back (slide_jog)


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


def wall_strips(
    geoms: Sequence[RoomGeometry],
    accept: Callable[[WallSegment], bool],
    blocked: Sequence[Polygon] = (),
    inner: bool = False,
) -> list[Polygon]:
    """Bands of walls between rooms of the flat through the whole wall thickness, for walls that
    accept() lets through; without windows and without the blocked bands (openings). inner=True
    means walls inside one room (the same room on both sides). Outer walls (no room beyond) are
    never in. A shared wall is described in both rooms, so its bands are merged: one wall, one
    band."""
    cut = shapely.unary_union(list(blocked)).buffer(1.0) if blocked else None
    out: list[Polygon] = []
    for g in geoms:
        for seg in g.contour.segments:
            if not accept(seg):
                continue
            probe = seg.point_at(seg.length / 2) + seg.outward * (seg.thickness + 50.0)
            beyond = [o for o in geoms if point_in_polygon(probe, o.contour.vertices)]
            if not beyond:
                continue
            within = all(o is g for o in beyond)
            if within != inner or (within and not seg.partition):
                continue
            out_v = seg.outward * seg.thickness
            strip: BaseGeometry = Polygon(
                [
                    seg.start.as_tuple(),
                    seg.end.as_tuple(),
                    (seg.end + out_v).as_tuple(),
                    (seg.start + out_v).as_tuple(),
                ]
            )
            for op in g.room.openings:
                if op.wall == seg.id and op.type is OpeningType.WINDOW:
                    strip = strip.difference(opening_strip(g, op))
            if cut is not None:
                strip = strip.difference(cut)
            out += _polygons(strip)
    return _polygons(shapely.unary_union(out)) if out else []


def _polygons(geom: BaseGeometry) -> list[Polygon]:
    parts = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
    return [p for p in parts if isinstance(p, Polygon) and p.area > 1.0]


def drillable(seg: WallSegment) -> bool:
    """A wall a cable may go through: not load-bearing and no thicker than WALL_DRILL_MAX, or
    explicitly a partition."""
    return not seg.bearing and (seg.thickness <= WALL_DRILL_MAX or seg.partition)


def drillable_walls(geoms: Sequence[RoomGeometry]) -> list[Polygon]:
    """Walls between rooms that a route may cross (drillable), without doors and openings: those
    are bands of their own (ceiling_passes) or free passes (floor)."""
    openings = [
        opening_strip(g, op)
        for g in geoms
        for op in g.room.openings
        if op.type is not OpeningType.WINDOW
    ]
    return wall_strips(geoms, drillable, openings)


def below_ceiling(op: Opening, ceiling: float) -> bool:
    """A door or an opening with wall above it: its top (DOOR_TOP_MM without a height) is lower
    than the ceiling, so a ceiling route passing it drills that wall (decision 2026-11-23)."""
    if op.type is OpeningType.WINDOW:
        return False
    top = op.height if op.height is not None else DOOR_TOP_MM
    return top < ceiling


def ceiling_passes(geoms: Sequence[RoomGeometry], ceiling: float) -> list[Polygon]:
    """Strips of doors and openings lower than the ceiling, merged: on the ceiling plane each is
    a band that costs WALL_PASS_COST to cross, like a drillable wall (decision 2026-11-23). A door
    and the opening of the neighbour at the same spot merge into one band."""
    strips = [
        opening_strip(g, op) for g in geoms for op in g.room.openings if below_ceiling(op, ceiling)
    ]
    return _polygons(shapely.unary_union(strips)) if strips else []


def crossings(path: Sequence[Vec], bands: Sequence[Polygon]) -> list[Crossing]:
    """Pieces of a route across the bands (walls or openings), each as its two ends: the holes the
    route makes, in path order."""
    if len(path) < 2 or not bands:
        return []
    line = LineString([v.as_tuple() for v in path])
    out: list[Crossing] = []
    for band in bands:
        cut = line.intersection(band)
        for piece in getattr(cut, "geoms", [cut]):
            if isinstance(piece, LineString) and piece.length > 1.0:
                (x0, y0), (x1, y1) = piece.coords[0], piece.coords[-1]
                out.append((Vec(x0, y0), Vec(x1, y1)))
    return out


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
    penalty: dict[int, float] | None = None  # extra cost to enter a cell, mm (wall bands, plumbing)
    mult: list[float] | None = None  # cost per mm of a step into the cell (sewer: cheaper by walls)
    tag: list[int] | None = None  # cell kind for pruning in the search (sewer, network)
    # Cells closer than APART to a power cable going along x and along y (apart_cells): a step
    # the same way there costs APART_COST more
    apart: tuple[frozenset[int], frozenset[int]] | None = None
    # Band cells at a ready hole (HOLE_CELL_COST instead of the pass): the route is free there
    opened: frozenset[int] = field(default_factory=frozenset)

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

    def index(self, p: Vec) -> int:
        """Cell index of a cell centre (center inverted)."""
        return round((p.y - self.y0) / STEP) * self.nx + round((p.x - self.x0) / STEP)

    def center(self, idx: int) -> Vec:
        iy, ix = divmod(idx, self.nx)
        return Vec(self.x0 + ix * STEP, self.y0 + iy * STEP)

    def nearest_free(self, p: Vec, open_only: bool = False) -> int:
        """Free cell nearest to the point; open_only: a cell without a penalty first (a route end
        is in the room, not in the band of a wall it stands on), any free one if there is none."""
        if open_only and self.penalty:
            penalty = self.penalty
            try:
                return self._nearest(p, lambda k: self.free[k] and k not in penalty)
            except ValueError:
                pass
        return self._nearest(p, lambda k: self.free[k])

    def _nearest(self, p: Vec, ok: Callable[[int], bool]) -> int:
        best, best_d = -1, float("inf")
        cx = round((p.x - self.x0) / STEP)
        cy = round((p.y - self.y0) / STEP)
        for r in range(max(self.nx, self.ny)):
            for iy in range(cy - r, cy + r + 1):
                for ix in range(cx - r, cx + r + 1):
                    if max(abs(ix - cx), abs(iy - cy)) != r:
                        continue
                    if 0 <= ix < self.nx and 0 <= iy < self.ny and ok(iy * self.nx + ix):
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
                nxt = jy * self.nx + jx
                ns = nxt * 4
                c = cost + (diagonal if dx and dy else STEP)
                if self.penalty is not None:
                    c += self.penalty.get(nxt, 0.0)
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
                if self.apart is not None:
                    beside = self.apart[0 if dy == 0 else 1]
                    if nxt in beside or cell in beside:
                        c += APART_COST
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


def slide_jog(path: Sequence[Vec], grid: Grid) -> list[Vec]:
    """Move the short jog at the target end of a route back from the point as far as the free
    area allows.

    The search runs on cell centres; a point off them (a socket at x=3965 by a 3950 column) or a
    point the route cannot run straight to (a wall end within CLEARANCE of its line) is joined by
    a short jog (at most JOG_MAX) right at the wall: on the elevations, where every turn is
    rounded with the cable's radius, it is a zigzag at the drop. Here the piece before the jog is
    slid over to the point's line: the jog goes to the farthest spot of that piece from which the
    route runs on the point's line within the area at least CLEARANCE from walls (Grid.inner),
    and if the whole piece fits it disappears. The length stays the same, the turns do not grow.
    A low-voltage route does not slide onto cells beside power (Grid.apart). Only the target end
    and only a short jog: a long piece there is a run of its own, often in a bundle."""
    pts = list(reversed(path))
    if grid.inner is None or len(pts) < 4:
        return list(path)
    node, b, a, p1 = pts[0], pts[1], pts[2], pts[3]
    approach, jog, back = b - node, a - b, p1 - a
    if not (_axis(approach) and _axis(jog) and _axis(back)):
        return list(path)
    if _axis(approach) != _axis(back) or _axis(jog) == _axis(back):
        return list(path)
    if approach.dot(back) <= 0 or jog.length() > JOG_MAX + 1e-6:
        return list(path)
    span = back.length()
    u = back * (1 / span)
    tries = [span, *(k * STEP for k in range(math.floor((span - 1e-6) / STEP), 0, -1))]
    for s in tries:
        j1 = a + u * s
        j2 = j1 - jog
        if _clear(grid, j1, j2) and _clear(grid, j2, b):
            return list(reversed(simplify([node, j2, j1, *pts[3:]])))
    return list(path)


def _axis(d: Vec) -> str | None:
    """Axis of a piece: "h" or "v", None for a slanted or zero piece."""
    if abs(d.y) <= 1e-6 < abs(d.x):
        return "h"
    if abs(d.x) <= 1e-6 < abs(d.y):
        return "v"
    return None


def _clear(grid: Grid, a: Vec, b: Vec) -> bool:
    """A straight piece within the area at least CLEARANCE from walls and, for a low-voltage
    route, not along a power cable closer than APART."""
    if (b - a).length() <= 1e-6:
        return True
    assert grid.inner is not None
    if not grid.inner.covers(shapely.LineString([a.as_tuple(), b.as_tuple()])):
        return False
    if grid.apart is None:
        return True
    near = grid.apart[0] if _axis(b - a) == "h" else grid.apart[1]
    n = max(1, math.ceil((b - a).length() / STEP))
    for k in range(n + 1):
        p = a + (b - a) * (k / n)
        ix = round((p.x - grid.x0) / STEP)
        iy = round((p.y - grid.y0) / STEP)
        if 0 <= ix < grid.nx and 0 <= iy < grid.ny and iy * grid.nx + ix in near:
            return False
    return True


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
    (economy): the shortest path is pulled tight instead of running at 90°. walls are bands of
    drillable walls (drillable_walls) and passes the strips of openings lower than the ceiling
    (ceiling_passes, only for a router of the ceiling plane): open, but a pass costs
    WALL_PASS_COST per cell; the pull stays in the area itself, so it does not cut through a wall
    where the search did not. holes are crossings of lines already routed on this plane and
    circuit (crossings): the band within WALL_HOLE_SHARE of each is free; own are those of them
    made by lines of the same source, cheaper by the tie-break (HOLE_CELL_COST). beside are the
    routes of power cables a low-voltage route keeps APART from (apart_cells), except within
    PANEL_FREE of calm (the panel); at any angle they are not looked at."""

    def __init__(
        self,
        area: BaseGeometry,
        source: End,
        any_angle: bool = False,
        walls: Sequence[Polygon] = (),
        beside: Sequence[Sequence[Vec]] = (),
        calm: Vec | None = None,
        passes: Sequence[Polygon] = (),
        holes: Sequence[Crossing] = (),
        own: Sequence[Crossing] = (),
    ) -> None:
        self.area = area
        self.walls = tuple(walls)
        self.passes = tuple(passes)
        self.holes = tuple(holes)
        self.own = tuple(c for c in own if c in self.holes)
        self.source = source
        self.any_angle = any_angle
        self.beside = () if any_angle else tuple(tuple(path) for path in beside)
        self.calm = calm if self.beside else None
        inputs = _Inputs(
            area,
            source,
            any_angle,
            self.walls,
            self.beside,
            self.calm,
            self.passes,
            self.holes,
            self.own,
        )
        memo = _MEMO.get()
        if memo is None:
            found = _searched(inputs)
        else:
            key = inputs.key()
            found = memo.searches.get(key) or memo.searches.setdefault(key, _searched(inputs))
        self.grid, self.start, self.prev, self.dist = found

    @property
    def bands(self) -> tuple[Polygon, ...]:
        """What a route pays to cross: drillable walls and, on the ceiling, openings."""
        return (*self.walls, *self.passes)

    def apart_from(self, beside: Sequence[Sequence[Vec]], calm: Vec | None = None) -> Router:
        """The same router for a low-voltage cable that keeps APART from the given power
        routes, but not within PANEL_FREE of calm (the panel); itself when there is nothing to
        keep from (or at any angle)."""
        if not beside or self.any_angle:
            return self
        return Router(
            self.area,
            self.source,
            self.any_angle,
            self.walls,
            beside,
            calm,
            self.passes,
            self.holes,
            self.own,
        )

    def with_holes(self, holes: Sequence[Crossing], own: Sequence[Crossing] = ()) -> Router:
        """The same router with these ready holes (own: those made by lines of its source); itself
        when it has no bands to open or already has them."""
        holes, own = tuple(holes), tuple(c for c in own if c in holes)
        if not self.bands or (holes, own) == (self.holes, self.own):
            return self
        return Router(
            self.area,
            self.source,
            self.any_angle,
            self.walls,
            self.beside,
            self.calm,
            self.passes,
            holes,
            own,
        )

    def rebased(self, source: End, beside: Sequence[Sequence[Vec]] = ()) -> Router:
        """The same area, bands and holes from another source, kept APART from beside (box leads,
        wiring_routes._via_lead) instead of its own; itself when nothing changes."""
        if source == self.source and not beside and not self.beside:
            return self
        return Router(
            self.area,
            source,
            self.any_angle,
            self.walls,
            beside,
            None,
            self.passes,
            self.holes,
            self.own,
        )

    def cost(self, node: Vec) -> float:
        """Route cost to the point (with turns); infinity if unreachable."""
        cell = self.grid.nearest_free(node, open_only=True)
        costs = [self.dist[s] for s in range(cell * 4, cell * 4 + 4) if s in self.dist]
        return min(costs, default=float("inf"))

    def route(
        self, target: End, before: Sequence[Vec] = (), after: Sequence[Vec] = ()
    ) -> list[Vec]:
        """The route to target; before and after are straight pieces added at its ends (the lead
        out of a box, wiring_routes._one_side), kept in the route and its trace."""
        cell = self.grid.nearest_free(target.node, open_only=True)
        cells = self.grid.path(self.prev, self.dist, cell)
        middle = self.grid.pull(cells) if self.any_angle else cells
        head = _join(self.source.node, middle[0], self.source.vertical_wall)
        tail = list(reversed(_join(target.node, middle[-1], target.vertical_wall)))
        out = simplify([*before, *head, *middle, *tail, *after])
        if not self.any_angle:
            out = slide_jog(out, self.grid)
        if trace.on():
            trace.emit(
                RouteTrace(
                    self.area,
                    self.walls,
                    self.grid,
                    self.start,
                    cell,
                    self.dist,
                    self.source.node,
                    target.node,
                    tuple(cells),
                    tuple(out),
                    self.cost(target.node),
                    self.any_angle,
                    self.passes,
                    self.holes,
                    self.own,
                )
            )
        return out


@dataclass(frozen=True)
class RouteTrace:
    """One routed line for the debug trace (trace.py): the router's area and grid, the search
    costs from its source, the grid path before pull and the final route. Shared with the router,
    not copied: read only."""

    area: BaseGeometry
    walls: tuple[Polygon, ...]
    grid: Grid
    start: int  # source cell
    target: int  # target cell
    dist: dict[int, float]  # search cost of each state (cell · 4 + direction)
    source: Vec
    end: Vec
    cells: tuple[Vec, ...]  # cell centres of the found path, before pull and the end joins
    path: tuple[Vec, ...]  # the route as returned
    cost: float  # search cost to the target, mm of cable with turn and wall penalties
    any_angle: bool
    passes: tuple[Polygon, ...] = ()  # openings lower than the ceiling (a ceiling router)
    holes: tuple[Crossing, ...] = ()  # ready holes the router saw
    own: tuple[Crossing, ...] = ()  # those of them made by lines of the same source

    def cell_cost(self, idx: int) -> float:
        """Cheapest search cost to the cell over its directions; infinity if unreached."""
        return min(
            (self.dist[s] for s in range(idx * 4, idx * 4 + 4) if s in self.dist),
            default=float("inf"),
        )

    @property
    def wall_cells(self) -> int:
        """Path cells in the band of a drillable wall: more than 0 means the route goes through
        a wall (paid or through a ready hole)."""
        return self._in_band(self.walls)

    @property
    def pass_cells(self) -> int:
        """Path cells in the band of an opening lower than the ceiling: the route passes above a
        door or an opening."""
        return self._in_band(self.passes)

    @property
    def hole_cells(self) -> int:
        """Path cells in a band at a ready hole: the route followed a line routed before."""
        return sum(1 for c in self.cells if self.grid.index(c) in self.grid.opened)

    def _in_band(self, strips: Sequence[Polygon]) -> int:
        if not strips or not self.cells:
            return 0
        zone = shapely.unary_union(list(strips)).buffer(CLEARANCE)
        hit = shapely.contains_xy(zone, [c.x for c in self.cells], [c.y for c in self.cells])
        return int(sum(bool(h) for h in hit))


@dataclass(frozen=True)
class _Inputs:
    """What a search depends on; equal inputs give the same search (search_memo)."""

    area: BaseGeometry
    source: End
    any_angle: bool
    walls: tuple[Polygon, ...]
    beside: tuple[tuple[Vec, ...], ...]
    calm: Vec | None
    passes: tuple[Polygon, ...]
    holes: tuple[Crossing, ...]
    own: tuple[Crossing, ...]

    def key(self) -> tuple[object, ...]:
        return (
            self.area.wkb,
            self.source.node.as_tuple(),
            self.source.vertical_wall,
            self.any_angle,
            tuple(w.wkb for w in self.walls),
            tuple(tuple(p.as_tuple() for p in path) for path in self.beside),
            None if self.calm is None else self.calm.as_tuple(),
            tuple(p.wkb for p in self.passes),
            tuple((a.as_tuple(), b.as_tuple()) for a, b in self.holes),
            tuple((a.as_tuple(), b.as_tuple()) for a, b in self.own),
        )

    def grid_key(self) -> tuple[object, ...]:
        """What the base grid depends on: the area and its bands, before holes and power beside."""
        return (
            self.area.wkb,
            tuple(w.wkb for w in self.walls),
            tuple(p.wkb for p in self.passes),
        )


# A searched router: grid, start cell, state parents and costs. Read only after the search, so
# routers with the same inputs share it.
_Search = tuple["Grid", int, dict[int, int], dict[int, float]]


@dataclass
class _Memo:
    """Searches by their inputs and base grids (free cells and band penalties) by area and bands:
    a search with new holes or power beside reuses the grid and only runs Dijkstra again."""

    searches: dict[tuple[object, ...], _Search] = field(default_factory=dict)
    grids: dict[tuple[object, ...], Grid] = field(default_factory=dict)


_MEMO: ContextVar[_Memo | None] = ContextVar("routing_memo", default=None)


@contextmanager
def search_memo() -> Iterator[None]:
    """Remember router searches by their exact inputs (area, source, angle, walls, openings,
    holes, power routes beside) until the block ends: one build routes the chosen variant and its
    neighbours, and most of their routers are the same (variant_block). Outside the block nothing
    is remembered, so a long-running service holds no searches between builds; a nested block uses
    the outer one."""
    if _MEMO.get() is not None:
        yield
        return
    token = _MEMO.set(_Memo())
    try:
        yield
    finally:
        _MEMO.reset(token)


def _searched(inputs: _Inputs) -> _Search:
    base = _base_grid(inputs)
    grid = replace(base, penalty=None if base.penalty is None else dict(base.penalty))
    if inputs.holes and grid.penalty:
        grid.opened = _opened(grid, inputs.holes)
        for k in grid.opened:
            grid.penalty[k] = 2 * HOLE_CELL_COST
        if inputs.own:
            for k in _opened(grid, inputs.own):
                grid.penalty[k] = HOLE_CELL_COST
    if inputs.beside:
        grid.apart = apart_cells(grid, inputs.beside, inputs.calm)
    start = grid.nearest_free(inputs.source.node, open_only=True)
    search = grid.search_any if inputs.any_angle else grid.search
    prev, dist = search(start)
    return grid, start, prev, dist


def _base_grid(inputs: _Inputs) -> Grid:
    """Grid of the area with its bands open and their pass penalties, shared by every search over
    the same area and bands (search_memo): read only, a search copies the penalties it changes."""
    memo = _MEMO.get()
    key = inputs.grid_key()
    if memo is not None and key in memo.grids:
        return memo.grids[key]
    if inputs.walls:
        grid = Grid.of(shapely.unary_union([inputs.area, *inputs.walls]))
        grid.inner = Grid.of(inputs.area).inner
    else:
        grid = Grid.of(inputs.area)
    if inputs.walls or inputs.passes:
        grid.penalty = _wall_penalty(grid, inputs.walls)
        for k, cost in _wall_penalty(grid, inputs.passes, WALL_PASS_COST - PASS_FAVOUR).items():
            grid.penalty[k] = max(grid.penalty.get(k, 0.0), cost)
    if memo is not None:
        memo.grids[key] = grid
    return grid


def _wall_penalty(
    grid: Grid, walls: Sequence[Polygon], pass_cost: float = WALL_PASS_COST
) -> dict[int, float]:
    """Free cells in the band of a wall widened by CLEARANCE on each side: pass_cost spread over
    the cells across the band, so a pass costs about the same through any thickness. Where bands
    overlap (a door strip and the wall it sits in) the cost is the maximum, not a sum."""
    idx = [k for k, ok in enumerate(grid.free) if ok]
    xs = [grid.center(k).x for k in idx]
    ys = [grid.center(k).y for k in idx]
    out: dict[int, float] = {}
    for wall in walls:
        thickness = 2 * wall.area / wall.length  # a long thin band (or an L of two)
        cost = pass_cost * STEP / (thickness + 2 * CLEARANCE)
        inside = shapely.contains_xy(wall.buffer(CLEARANCE), xs, ys)
        for k, hit in zip(idx, inside, strict=True):
            if hit:
                out[k] = max(out.get(k, 0.0), cost)
    return out


def _opened(grid: Grid, holes: Sequence[Crossing]) -> frozenset[int]:
    """Band cells within WALL_HOLE_SHARE of a ready hole (the crossing piece of a routed line):
    free for the next lines, as the estimate counts them in the same hole."""
    if not holes:
        return frozenset()
    assert grid.penalty is not None
    idx = sorted(grid.penalty)
    zone = shapely.unary_union([LineString([a.as_tuple(), b.as_tuple()]) for a, b in holes]).buffer(
        WALL_HOLE_SHARE
    )
    xs = [grid.center(k).x for k in idx]
    ys = [grid.center(k).y for k in idx]
    hit = shapely.contains_xy(zone, xs, ys)
    return frozenset(k for k, h in zip(idx, hit, strict=True) if h)


def apart_cells(
    grid: Grid, paths: Sequence[Sequence[Vec]], calm: Vec | None = None
) -> tuple[frozenset[int], frozenset[int]]:
    """Free cells closer than APART to a piece of the routes: beside a piece along x (first set)
    and beside a piece along y (second). Slanted pieces are skipped; cells closer than
    PANEL_FREE to calm (the panel) are not in either set."""
    along_x: set[int] = set()
    along_y: set[int] = set()
    reach = APART - 1e-6

    def cells(lo_x: float, hi_x: float, lo_y: float, hi_y: float) -> list[int]:
        ix0 = max(math.ceil((lo_x - reach - grid.x0) / STEP), 0)
        ix1 = min(math.floor((hi_x + reach - grid.x0) / STEP), grid.nx - 1)
        iy0 = max(math.ceil((lo_y - reach - grid.y0) / STEP), 0)
        iy1 = min(math.floor((hi_y + reach - grid.y0) / STEP), grid.ny - 1)
        return [
            iy * grid.nx + ix
            for iy in range(iy0, iy1 + 1)
            for ix in range(ix0, ix1 + 1)
            if grid.free[iy * grid.nx + ix] and not near_panel(iy * grid.nx + ix)
        ]

    def near_panel(k: int) -> bool:
        if calm is None:
            return False
        c = grid.center(k)
        return math.hypot(c.x - calm.x, c.y - calm.y) < PANEL_FREE

    for path in paths:
        for a, b in itertools.pairwise(path):
            lo_x, hi_x = min(a.x, b.x), max(a.x, b.x)
            lo_y, hi_y = min(a.y, b.y), max(a.y, b.y)
            if hi_y - lo_y <= 0.5 < hi_x - lo_x:
                along_x.update(cells(lo_x, hi_x, lo_y, hi_y))
            elif hi_x - lo_x <= 0.5 < hi_y - lo_y:
                along_y.update(cells(lo_x, hi_x, lo_y, hi_y))
    return frozenset(along_x), frozenset(along_y)


def beside_mm(path: Sequence[Vec], others: Sequence[Sequence[Vec]]) -> float:
    """How much of a route at right angles runs the same way as the other routes closer than
    APART, mm: what a low-voltage cable could not keep apart from power."""
    total = 0.0
    spans: dict[bool, list[tuple[float, float, float]]] = {True: [], False: []}
    for other in others:
        for a, b in itertools.pairwise(other):
            if abs(a.y - b.y) <= 0.5 < abs(a.x - b.x):
                spans[True].append((a.y, min(a.x, b.x), max(a.x, b.x)))
            elif abs(a.x - b.x) <= 0.5 < abs(a.y - b.y):
                spans[False].append((a.x, min(a.y, b.y), max(a.y, b.y)))
    for a, b in itertools.pairwise(path):
        horizontal = abs(a.y - b.y) <= 0.5 < abs(a.x - b.x)
        if not horizontal and not (abs(a.x - b.x) <= 0.5 < abs(a.y - b.y)):
            continue
        fixed = a.y if horizontal else a.x
        lo, hi = (min(a.x, b.x), max(a.x, b.x)) if horizontal else (min(a.y, b.y), max(a.y, b.y))
        near = sorted(
            (max(lo, s_lo), min(hi, s_hi))
            for s_fixed, s_lo, s_hi in spans[horizontal]
            if abs(s_fixed - fixed) < APART - 1e-6 and min(hi, s_hi) > max(lo, s_lo)
        )
        end = lo
        for s_lo, s_hi in near:
            total += max(s_hi - max(s_lo, end), 0.0)
            end = max(end, s_hi)
    return total


def length(path: Sequence[Vec]) -> float:
    """Route length on the plan; pieces at any angle (the same for right angles)."""
    return sum(math.hypot(b.x - a.x, b.y - a.y) for a, b in itertools.pairwise(path))


def is_ortho(path: Sequence[Vec], tol: float = 0.5) -> bool:
    """All pieces run along the axes (standard and premium)."""
    return all(abs(a.x - b.x) <= tol or abs(a.y - b.y) <= tol for a, b in itertools.pairwise(path))
