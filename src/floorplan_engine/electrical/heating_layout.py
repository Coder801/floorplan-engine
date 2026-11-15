"""Floor heating cable as a serpentine (decision 2026-11-14): straight runs along one room axis,
pitch apart, each turn a half circle of radius pitch / 2: run → turn → next run.

Geometry only, no ezdxf. The heated area is any region: a rectangle, an L or U shape, a zone
closed by a slanted line, minus exclusions; runs stay along the plan axes, a slanted edge cuts
them stepwise. Runs lie on rows across it — the same row grid
for the whole region, rows centred so the margins at both far edges are equal. A row may cross
the region in several pieces (a U shape across its arms); pieces of neighbouring rows that face
each other one to one make a cell (boustrophedon decomposition). One continuous cable goes
cell by cell: the last run of a cell turns into the first run of a neighbouring cell's end row,
on the side the run came to. The cell order is a search over the few cells: all of them if it
can, otherwise the most (the rest is reported as not covered). Where two rows of different width
meet, the turn sits inside both, so the wider row loses its overhang near the turn.

Both run directions are tried; runs along the long side first (fewer turns). Everything is
deterministic: the same region and pitch give the same cable.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.model.geometry import Vec

EPS = 1e-6
SEARCH_LIMIT = 20_000  # cell orders tried at most: a region has a handful of cells
Interval = tuple[float, float]


@dataclass(frozen=True)
class Straight:
    a: Vec
    b: Vec

    @property
    def length(self) -> float:
        return (self.b - self.a).length()

    def cut(self, length: float) -> Straight:
        """The first length mm of the run."""
        d = self.b - self.a
        k = 0.0 if self.length < EPS else min(1.0, length / self.length)
        return Straight(self.a, self.a + d * k)


@dataclass(frozen=True)
class Arc:
    """Turn: from start_deg by sweep_deg (positive counterclockwise), model mm and degrees."""

    center: Vec
    radius: float
    start_deg: float
    sweep_deg: float

    @property
    def length(self) -> float:
        return self.radius * math.radians(abs(self.sweep_deg))

    def at(self, deg: float) -> Vec:
        a = math.radians(deg)
        return self.center + Vec(math.cos(a), math.sin(a)) * self.radius

    @property
    def a(self) -> Vec:
        return self.at(self.start_deg)

    @property
    def b(self) -> Vec:
        return self.at(self.start_deg + self.sweep_deg)

    def cut(self, length: float) -> Arc:
        k = 0.0 if self.length < EPS else min(1.0, length / self.length)
        return Arc(self.center, self.radius, self.start_deg, self.sweep_deg * k)

    def ccw(self) -> tuple[float, float]:
        """Start and end angle counterclockwise, as a DXF ARC wants them."""
        if self.sweep_deg >= 0:
            return self.start_deg, self.start_deg + self.sweep_deg
        return self.start_deg + self.sweep_deg, self.start_deg


Piece = Straight | Arc


@dataclass(frozen=True)
class Visit:
    """A run on a row: row coordinate v, from u0 to u1 (run direction is u0 → u1)."""

    v: float
    u0: float
    u1: float


@dataclass(frozen=True)
class Serpentine:
    """The whole cable route at one pitch: pieces in order from the start; along_x — runs along X.
    cells and covered — how many cells the region has and how many the cable goes through."""

    pieces: tuple[Piece, ...]
    pitch: float
    along_x: bool
    visits: tuple[Visit, ...]  # runs in order, in the run frame (u along the runs)
    cells: int
    covered: int

    @property
    def length(self) -> float:
        return sum(p.length for p in self.pieces)

    @property
    def start(self) -> Vec:
        return self.pieces[0].a

    @property
    def start_out(self) -> Vec:
        """Direction from the start out of the zone: against the first run."""
        first = self.visits[0]
        sign = -1.0 if first.u1 >= first.u0 else 1.0
        return Vec(sign, 0.0) if self.along_x else Vec(0.0, sign)

    def xy(self, u: float, v: float) -> Vec:
        return Vec(u, v) if self.along_x else Vec(v, u)

    def truncated(self, length: float) -> Serpentine:
        """The route cut at length mm from the start (the cable ends there); longer — as is."""
        out: list[Piece] = []
        left = length
        for p in self.pieces:
            if left <= EPS:
                break
            out.append(p if p.length <= left else p.cut(left))
            left -= p.length
        return Serpentine(
            tuple(out), self.pitch, self.along_x, self.visits, self.cells, self.covered
        )


# --- Region slices -------------------------------------------------------------------------


def _swap(region: BaseGeometry) -> BaseGeometry:
    """Mirror over y = x: runs along Y become runs along X."""
    return affinity.affine_transform(region, [0.0, 1.0, 1.0, 0.0, 0.0, 0.0])


def _intervals(geom: BaseGeometry) -> list[Interval]:
    out: list[Interval] = []
    parts = getattr(geom, "geoms", [geom])
    for g in parts:
        if isinstance(g, LineString) and g.length > EPS:
            xs = [c[0] for c in g.coords]
            out.append((min(xs), max(xs)))
        elif hasattr(g, "geoms"):
            out += _intervals(g)
    return _merge(out)


def _merge(items: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for lo, hi in sorted(items):
        if out and lo <= out[-1][1] + EPS:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def _slice(region: BaseGeometry, v: float) -> list[Interval]:
    """The region on the line y = v: pieces along x."""
    x0, _, x1, _ = region.bounds
    return _intervals(region.intersection(LineString([(x0 - 1, v), (x1 + 1, v)])))


def _cross(a: list[Interval], b: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for lo, hi in a:
        for lo2, hi2 in b:
            if min(hi, hi2) - max(lo, lo2) > EPS:
                out.append((max(lo, lo2), min(hi, hi2)))
    return out


def _band(region: BaseGeometry, va: float, vb: float, ys: Sequence[float]) -> list[Interval]:
    """Where a segment from row va to row vb fits whole inside the region: the slices at both
    rows and on both sides of every vertex between them."""
    lo, hi = min(va, vb), max(va, vb)
    out = _cross(_slice(region, lo), _slice(region, hi))
    for y in ys:
        if lo < y < hi:
            out = _cross(out, _slice(region, y - 1e-3))
            out = _cross(out, _slice(region, y + 1e-3))
    return out


def _vertex_ys(region: BaseGeometry) -> list[float]:
    polys = region.geoms if isinstance(region, MultiPolygon) else [region]
    ys: set[float] = set()
    for p in polys:
        if isinstance(p, Polygon):
            for ring in (p.exterior, *p.interiors):
                ys |= {round(c[1], 6) for c in ring.coords}
    return sorted(ys)


def rows_of(span: tuple[float, float], pitch: float) -> list[float]:
    """Row coordinates across a span: as many as fit at the pitch, centred (equal margins)."""
    lo, hi = span
    n = max(1, math.floor((hi - lo) / pitch + EPS))
    margin = (hi - lo - (n - 1) * pitch) / 2
    return [lo + margin + k * pitch for k in range(n)]


# --- Cells and their order -----------------------------------------------------------------


@dataclass(frozen=True)
class _Cell:
    first: int  # row index of its first row
    pieces: tuple[Interval, ...]  # one per row, rows first … first + len − 1

    @property
    def last(self) -> int:
        return self.first + len(self.pieces) - 1


@dataclass
class _Grid:
    region: BaseGeometry
    rows: list[float]
    pieces: list[list[Interval]]
    ys: list[float]
    pitch: float

    def link(self, k: int, a: Interval, b: Interval) -> Interval | None:
        """Band between row k (piece a) and row k + 1 (piece b) where a turn fits: the widest
        common part, at least a pitch wide."""
        best: Interval | None = None
        for lo, hi in _band(self.region, self.rows[k], self.rows[k + 1], self.ys):
            lo2, hi2 = max(lo, a[0], b[0]), min(hi, a[1], b[1])
            if hi2 - lo2 >= self.pitch - EPS and (best is None or hi2 - lo2 > best[1] - best[0]):
                best = (lo2, hi2)
        return best


def _cells(grid: _Grid) -> list[_Cell]:
    """Pieces of neighbouring rows that face each other one to one go into one cell."""
    nexts: dict[tuple[int, int], list[int]] = {}
    prevs: dict[tuple[int, int], list[int]] = {}
    for k in range(len(grid.rows) - 1):
        for i, a in enumerate(grid.pieces[k]):
            for j, b in enumerate(grid.pieces[k + 1]):
                if grid.link(k, a, b) is not None:
                    nexts.setdefault((k, i), []).append(j)
                    prevs.setdefault((k + 1, j), []).append(i)
    cells: list[_Cell] = []
    open_cells: dict[tuple[int, int], list[Interval]] = {}  # last piece → its cell pieces
    starts: dict[tuple[int, int], int] = {}
    for k, row in enumerate(grid.pieces):
        for j, piece in enumerate(row):
            before = prevs.get((k, j), [])
            if len(before) == 1 and len(nexts.get((k - 1, before[0]), [])) == 1:
                key = (k - 1, before[0])
                chain = open_cells.pop(key)
                start = starts.pop(key)
            else:
                chain, start = [], k
            chain.append(piece)
            open_cells[(k, j)] = chain
            starts[(k, j)] = start
    for key in sorted(open_cells, key=lambda key: (starts[key], key[1])):
        cells.append(_Cell(starts[key], tuple(open_cells[key])))
    return sorted(cells, key=lambda c: (c.first, c.pieces[0][0]))


@dataclass(frozen=True)
class _Step:
    row: int
    piece: Interval


def _walk(cell: _Cell, from_first: bool) -> list[_Step]:
    steps = [_Step(cell.first + k, p) for k, p in enumerate(cell.pieces)]
    return steps if from_first else steps[::-1]


def _order(grid: _Grid, cells: list[_Cell], near: Vec | None) -> tuple[list[_Step], bool, int]:
    """Row visits through the most cells, then the start nearest `near`; and the start side
    (True — from the left, the first run goes towards +u) and how many cells were covered."""
    best: tuple[tuple[float, ...], list[_Step], bool, int] | None = None
    budget = [SEARCH_LIMIT]

    def score(steps: list[_Step], left: bool, n: int) -> tuple[float, ...]:
        first = steps[0]
        u = first.piece[0] if left else first.piece[1]
        dist = 0.0 if near is None else (Vec(u, grid.rows[first.row]) - near).length()
        return (-n, round(dist, 3))

    def extend(steps: list[_Step], used: frozenset[int], start_left: bool) -> None:
        # The turn into the next cell is on whatever side the last run came to: a band at least
        # a pitch wide holds it on either side, so only the band matters
        nonlocal best
        budget[0] -= 1
        found = False
        tail = steps[-1]
        for c, cell in enumerate(cells):
            if c in used or budget[0] <= 0:
                continue
            for from_first in (True, False):
                entry = cell.first if from_first else cell.last
                if abs(entry - tail.row) != 1 or (len(cell.pieces) == 1 and not from_first):
                    continue
                piece = cell.pieces[entry - cell.first]
                k = min(entry, tail.row)
                a, b = (tail.piece, piece) if tail.row == k else (piece, tail.piece)
                if grid.link(k, a, b) is None:
                    continue
                found = True
                extend([*steps, *_walk(cell, from_first)], used | {c}, start_left)
        if not found:
            key = score(steps, start_left, len(used))
            if best is None or key < best[0]:
                best = (key, steps, start_left, len(used))

    for c, cell in enumerate(cells):
        for from_first in (True, False):
            if len(cell.pieces) == 1 and not from_first:
                continue
            for left in (True, False):
                extend(_walk(cell, from_first), frozenset({c}), left)
    assert best is not None
    return best[1], best[2], best[3]


# --- Route -----------------------------------------------------------------------------------


def _route(grid: _Grid, steps: list[_Step], start_left: bool) -> tuple[list[Piece], list[Visit]]:
    """Runs and half-circle turns through the row visits, in the run frame (u, v)."""
    r = grid.pitch / 2
    turns: list[tuple[float, bool]] = []  # u of each turn and whether it is on the right
    left = start_left
    for s, t in pairwise(steps):
        k = min(s.row, t.row)
        a, b = (s.piece, t.piece) if s.row == k else (t.piece, s.piece)
        band = grid.link(k, a, b)
        assert band is not None
        on_right = left  # a run from the left ends on the right
        turns.append((band[1] - r if on_right else band[0] + r, on_right))
        left = not left
    pieces: list[Piece] = []
    visits: list[Visit] = []
    left = start_left
    for i, s in enumerate(steps):
        v = grid.rows[s.row]
        u0 = turns[i - 1][0] if i > 0 else (s.piece[0] if left else s.piece[1])
        u1 = turns[i][0] if i < len(turns) else (s.piece[1] if left else s.piece[0])
        if (u1 - u0) * (1 if left else -1) < 0:  # neighbours overlap at the far ends: no run
            u1 = u0
        visits.append(Visit(v, u0, u1))
        pieces.append(Straight(Vec(u0, v), Vec(u1, v)))
        if i < len(turns):
            u, on_right = turns[i]
            vn = grid.rows[steps[i + 1].row]
            up = vn > v
            start = -90.0 if up else 90.0
            sweep = (180.0 if up else -180.0) * (1 if on_right else -1)
            pieces.append(Arc(Vec(u, (v + vn) / 2), abs(vn - v) / 2, start, sweep))
        left = not left
    return pieces, visits


def _to_xy(p: Piece, along_x: bool) -> Piece:
    if along_x:
        return p
    if isinstance(p, Straight):
        return Straight(Vec(p.a.y, p.a.x), Vec(p.b.y, p.b.x))
    return Arc(Vec(p.center.y, p.center.x), p.radius, 90.0 - p.start_deg, -p.sweep_deg)


def serpentine(
    region: BaseGeometry, pitch: float, along_x: bool, near: Vec | None = None
) -> Serpentine | None:
    """The cable at this pitch with runs along X (along_x) or Y; near is where the cable should
    start (the controller): the start nearest to it among the orders through the most cells.
    None for an empty region."""
    if region.is_empty or region.area < EPS:
        return None
    frame = region if along_x else _swap(region)
    target = None if near is None else (near if along_x else Vec(near.y, near.x))
    _, y0, _, y1 = frame.bounds
    rows = rows_of((y0, y1), pitch)
    pieces = [[p for p in _slice(frame, v) if p[1] - p[0] >= pitch] for v in rows]
    grid = _Grid(frame, rows, pieces, _vertex_ys(frame), pitch)
    cells = _cells(grid)
    if not cells:
        return None
    steps, start_left, covered = _order(grid, cells, target)
    route, visits = _route(grid, steps, start_left)
    return Serpentine(
        tuple(_to_xy(p, along_x) for p in route),
        pitch,
        along_x,
        tuple(visits),
        len(cells),
        covered,
    )


def long_side_first(region: BaseGeometry) -> tuple[bool, bool]:
    """Run directions to try: along the longer side of the region first."""
    x0, y0, x1, y1 = region.bounds
    return (True, False) if x1 - x0 >= y1 - y0 else (False, True)
