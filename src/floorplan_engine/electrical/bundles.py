"""Bundles of routes on one line (decision 2026-10-24): the route pieces along the axes, the
pieces of a line on which the set of cables does not change and the lanes of a bundle (each
cable offset by LANE_MM on the sheet, a bundle at most BAND_MM wide, shifted away from walls).
The lanes keep the order the cables need further on (decision 2026-11-17, side): of two cables
on a bundle, the one that leaves it to the left (looking along the bundle) lies to the left all
along it, so cables leaving the panel already lie in the order of their turns and do not cross.
Cables that never part (the same way to one drop) keep their order by the way they go, not by
the axis (decision 2026-11-18, _tie): the later line to the left, so they do not cross at a turn.
Pure geometry, shared by the wiring drawing (lanes, length labels), the box placement
(box_spots.clear_boxes: a box keeps off the lanes of other lines), the fixings
(electrical/mounting.plan_fixings: the clips of a bundle go in one line) and the 3D scene."""

from __future__ import annotations

import functools
import itertools
import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry

from floorplan_engine.electrical.routing import CLEARANCE
from floorplan_engine.electrical.wiring_model import Run
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.scale import sheet

_TOL = 1.0  # model mm: points on one line
LANE_MM = 0.7  # cable lane step on the sheet (decision 2026-10-24)
BAND_MM = 14.0  # a bundle is no wider than this on the sheet: a big bundle gets a smaller step
WALL_CLEAR_MM = 0.4  # from the outermost bundle line to a wall on the sheet
_SAMPLES = (0.1, 0.3, 0.5, 0.7, 0.9)  # where to measure room to walls, fractions


@dataclass(frozen=True)
class Segment:
    """Straight route piece along an axis: axis "h" is horizontal (fixed = y), "v" is vertical
    (fixed = x); lo < hi are the end coordinates along the axis."""

    run: int
    index: int  # piece index in the route
    axis: str
    fixed: float
    lo: float
    hi: float


@dataclass(frozen=True)
class Bundle:
    """Line piece on which the set of cables does not change."""

    axis: str
    fixed: float
    lo: float
    hi: float
    runs: tuple[int, ...]
    band: tuple[float, float]  # offsets of the outermost lanes, model mm

    @property
    def length(self) -> float:
        return self.hi - self.lo


def segments(paths: Sequence[Sequence[Vec]]) -> list[Segment]:
    """Route pieces along the axes; slanted pieces (economy, routing.any_angle) are not bundled:
    lines from a box fan out to the points and do not share a lane."""
    out: list[Segment] = []
    for k, path in enumerate(paths):
        for i, (a, b) in enumerate(itertools.pairwise(path)):
            if abs(a.y - b.y) <= _TOL and abs(a.x - b.x) > _TOL:
                out.append(Segment(k, i, "h", round(a.y), min(a.x, b.x), max(a.x, b.x)))
            elif abs(a.x - b.x) <= _TOL and abs(a.y - b.y) > _TOL:
                out.append(Segment(k, i, "v", round(a.x), min(a.y, b.y), max(a.y, b.y)))
    return out


def by_line(segs: Iterable[Segment]) -> dict[tuple[str, float], list[Segment]]:
    lines: dict[tuple[str, float], list[Segment]] = defaultdict(list)
    for s in segs:
        lines[(s.axis, s.fixed)].append(s)
    return lines


def bundles(segs: Sequence[Segment], offsets: dict[tuple[int, int], float]) -> list[Bundle]:
    """Line pieces with a constant set of cables: cut points are the piece ends."""
    out: list[Bundle] = []
    for (axis, fixed), line in by_line(segs).items():
        cuts = sorted({c for s in line for c in (s.lo, s.hi)})
        for lo, hi in itertools.pairwise(cuts):
            here = [s for s in line if s.lo <= lo + _TOL and s.hi >= hi - _TOL]
            if not here or hi - lo <= _TOL:
                continue
            shifts = [offsets.get((s.run, s.index), 0.0) for s in here]
            runs = tuple(sorted({s.run for s in here}))
            out.append(Bundle(axis, fixed, lo, hi, runs, (min(shifts), max(shifts))))
    return out


def lane_paths(
    runs: Sequence[Run], free: BaseGeometry | None
) -> tuple[list[list[Vec]], list[Bundle]]:
    """Line paths with lane shifts and bundle pieces as on the wiring sheet, separately for
    ceiling and floor (line numbers in bundles index runs); free is the rooms and openings
    (Wiring.free), a bundle does not run onto walls."""
    paths: list[list[Vec]] = [list(r.path) for r in runs]
    plane_bundles: list[Bundle] = []
    for route in ("ceiling", "floor"):
        idx = [k for k, r in enumerate(runs) if r.route == route]
        segs = segments([runs[k].path for k in idx])
        margin = max(sheet(WALL_CLEAR_MM), CLEARANCE)  # bundle also stays CLEARANCE from walls
        room = clearance(free, margin) if free is not None else None
        offsets = lanes(segs, sheet(LANE_MM), sheet(BAND_MM), room, [runs[k].path for k in idx])
        for j, k in enumerate(idx):
            path = runs[k].path
            paths[k] = offset_path(path, [offsets.get((j, i), 0.0) for i in range(len(path) - 1)])
        plane_bundles += [
            Bundle(b.axis, b.fixed, b.lo, b.hi, tuple(idx[j] for j in b.runs), b.band)
            for b in bundles(segs, offsets)
        ]
    return paths, plane_bundles


# Room to walls on both sides of a line piece: (axis, coord, from, to) → (to −, to +), model mm
Room = Callable[[str, float, float, float], tuple[float, float]]


def clearance(free: BaseGeometry, margin: float) -> Room:
    """Room on both sides of a piece up to the edge of the free area (walls), minus margin: the
    smallest over several points along the piece; points outside the area do not count."""
    edge = free.boundary
    reach = 1e6

    def side(p: Point, d: tuple[float, float]) -> float:
        ray = LineString([(p.x, p.y), (p.x + d[0] * reach, p.y + d[1] * reach)])
        hit = ray.intersection(edge)
        return reach if hit.is_empty else p.distance(hit)

    def room(axis: str, fixed: float, lo: float, hi: float) -> tuple[float, float]:
        neg = pos = math.inf
        for t in _SAMPLES:
            v = lo + (hi - lo) * t
            p = Point(v, fixed) if axis == "h" else Point(fixed, v)
            if not free.contains(p):
                continue
            up, down = ((0.0, 1.0), (0.0, -1.0)) if axis == "h" else ((1.0, 0.0), (-1.0, 0.0))
            pos = min(pos, side(p, up) - margin)
            neg = min(neg, side(p, down) - margin)
        return max(neg, 0.0), max(pos, 0.0)

    return room


def lanes(
    segs: Sequence[Segment],
    pitch: float,
    band: float,
    room: Room | None = None,
    paths: Sequence[Sequence[Vec]] | None = None,
) -> dict[tuple[int, int], float]:
    """Offset of each piece from the line: (route, piece) → model mm, along +y for horizontal and
    +x for vertical. Lanes are computed per group of overlapping pieces of a line: overlapping
    ones go in different lanes, step pitch, the whole group no wider than band. With paths (the
    routes the pieces are of) the lanes keep the order the cables need where they leave the
    bundle (side); without them, the first free lane. room is the space to walls: the bundle is
    symmetric about the line, but next to a wall it shifts away; if there is less space than the
    bundle needs, the step shrinks and the bundle takes the full width."""
    out: dict[tuple[int, int], float] = {}
    for line in by_line(segs).values():
        for cluster in _overlapping(line):
            lane_of = _ordered(cluster, paths) if paths is not None else _first_free(cluster)
            count = max(lane_of.values()) + 1
            if count == 1:
                for key in lane_of:
                    out[key] = 0.0
                continue
            width = min(pitch * (count - 1), band)
            center = 0.0
            if room is not None:
                s0 = cluster[0]
                neg, pos = room(
                    s0.axis, s0.fixed, min(s.lo for s in cluster), max(s.hi for s in cluster)
                )
                if neg + pos < width:  # not enough room: smaller step, full width
                    width, center = neg + pos, (pos - neg) / 2
                else:  # next to a wall: shift away from it
                    center = min(max(0.0, width / 2 - neg), pos - width / 2)
            step = width / (count - 1)
            for key, n in lane_of.items():
                out[key] = center + (n - (count - 1) / 2) * step
    return out


def _first_free(cluster: Sequence[Segment]) -> dict[tuple[int, int], int]:
    """Interval colouring: each piece in the first lane free at its start."""
    ends: list[float] = []  # end of the last piece in each lane
    lane_of: dict[tuple[int, int], int] = {}
    for s in cluster:
        free = next((n for n, end in enumerate(ends) if end <= s.lo + _TOL), None)
        if free is None:
            free = len(ends)
            ends.append(s.hi)
        else:
            ends[free] = s.hi
        lane_of[(s.run, s.index)] = free
    return lane_of


def _ordered(
    cluster: Sequence[Segment], paths: Sequence[Sequence[Vec]]
) -> dict[tuple[int, int], int]:
    """Lanes in the order the cables leave the bundle, from − to + across it: each piece goes one
    lane past the pieces before it that it overlaps, so pieces that do not overlap may share a
    lane and overlapping ones keep their order."""

    def cmp(a: Segment, b: Segment) -> int:
        lo, hi = max(a.lo, b.lo), min(a.hi, b.hi)
        if hi - lo <= _TOL:
            return 0
        return side(paths, a, b, lo, hi) or _tie(paths, a, b)

    order = sorted(cluster, key=functools.cmp_to_key(cmp))
    lane_of: dict[tuple[int, int], int] = {}
    for n, s in enumerate(order):
        under = [
            lane_of[(t.run, t.index)] for t in order[:n] if min(s.hi, t.hi) - max(s.lo, t.lo) > _TOL
        ]
        lane_of[(s.run, s.index)] = max(under) + 1 if under else 0
    return lane_of


def _tie(paths: Sequence[Sequence[Vec]], a: Segment, b: Segment) -> int:
    """Order of two pieces whose routes never part (the same way to one drop): the later line
    lies to the left of the way its route goes, so the order holds through every turn and the
    cables do not cross (by the axis it flipped at each turn the other way). 1 if a lies on the +
    side of the line, −1 if b, 0 for one route."""
    if a.run == b.run:
        return 0
    path = paths[a.run]
    way = path[a.index + 1] - path[a.index]
    normal = Vec(0.0, 1.0) if a.axis == "h" else Vec(1.0, 0.0)
    left_is_plus = way.left().dot(normal) > 0
    return 1 if (a.run > b.run) == left_is_plus else -1


def side(paths: Sequence[Sequence[Vec]], a: Segment, b: Segment, lo: float, hi: float) -> int:
    """Which of two pieces lies on the + side of their line on their common stretch lo..hi: 1 if
    a, −1 if b, 0 if their routes never part to different sides. The routes are followed from the
    stretch both ways until they part (a route ending counts as going straight on): the one that
    turns to the left of the way it was going lies to the left all along their common way, the
    whole bundle included. If the two ends disagree (the cables cross anyway) the end ahead (+
    along the axis) decides."""
    along = Vec(1.0, 0.0) if a.axis == "h" else Vec(0.0, 1.0)
    normal = Vec(0.0, 1.0) if a.axis == "h" else Vec(1.0, 0.0)
    for d, end in ((along, hi), (along * -1.0, lo)):
        start = Vec(end, a.fixed) if a.axis == "h" else Vec(a.fixed, end)
        left = _parting(_walk(paths, a, d, start), _walk(paths, b, d, start), d)
        if left:
            return left if d.cross(normal) > 0 else -left
    return 0


def _walk(paths: Sequence[Sequence[Vec]], s: Segment, d: Vec, start: Vec) -> list[Vec]:
    """The route of piece s from start on its line onward in direction d: start, then the
    vertices past it."""
    path = paths[s.run]
    a, b = path[s.index], path[s.index + 1]
    if (b - a).dot(d) > 0:
        return [start, *path[s.index + 1 :]]
    return [start, *reversed(path[: s.index + 1])]


def _parting(wa: Sequence[Vec], wb: Sequence[Vec], d: Vec) -> int:
    """Two routes from one point in direction d, followed while they go together: 1 if route a
    then goes to the left of route b, −1 if to the right, 0 if they never part."""
    i = j = 0
    at, heading = wa[0], d
    for _ in range(len(wa) + len(wb)):
        da = _next(wa, i, at)
        db = _next(wb, j, at)
        if da is None or db is None or (da[0] - db[0]).length() > 1e-6:
            ta = heading.cross(da[0]) if da is not None else 0.0
            tb = heading.cross(db[0]) if db is not None else 0.0
            return (ta > tb + 1e-6) - (tb > ta + 1e-6)
        step = min(da[1], db[1])
        at, heading = at + da[0] * step, da[0]
        while i + 1 < len(wa) and (wa[i + 1] - at).length() <= _TOL:
            i += 1
        while j + 1 < len(wb) and (wb[j + 1] - at).length() <= _TOL:
            j += 1
    return 0


def _next(walk: Sequence[Vec], i: int, at: Vec) -> tuple[Vec, float] | None:
    """Direction (unit) and length from at to the next vertex of the walk past index i; None at
    the end of the route."""
    for p in walk[i + 1 :]:
        v = p - at
        n = v.length()
        if n > _TOL:
            return v * (1 / n), n
    return None


def _overlapping(line: Sequence[Segment]) -> list[list[Segment]]:
    """Line pieces in groups: in a group each overlaps at least one other (touching does not
    count).
    """
    groups: list[list[Segment]] = []
    reach = -math.inf
    for s in sorted(line, key=lambda s: (s.lo, s.hi, s.run)):
        if s.lo < reach - _TOL:
            groups[-1].append(s)
            reach = max(reach, s.hi)
        else:
            groups.append([s])
            reach = s.hi
    return groups


def offset_path(path: Sequence[Vec], shifts: Sequence[float]) -> list[Vec]:
    """Route with each piece shifted into its lane; a vertex between horizontal and vertical is the
    intersection of the shifted pieces, the ends move across their own piece."""
    if len(path) < 2:
        return list(path)

    def normal(i: int) -> Vec:
        a, b = path[i], path[i + 1]
        return Vec(0.0, 1.0) if abs(a.y - b.y) <= _TOL else Vec(1.0, 0.0)

    out = [path[0] + normal(0) * shifts[0]]
    for i in range(1, len(path) - 1):
        n_in, n_out = normal(i - 1), normal(i)
        p = path[i]
        if n_in == n_out:
            out.append(p + n_out * shifts[i])
        else:
            out.append(p + n_in * shifts[i - 1] + n_out * shifts[i])
    out.append(path[-1] + normal(len(path) - 2) * shifts[-1])
    return out
