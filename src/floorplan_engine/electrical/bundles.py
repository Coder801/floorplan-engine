"""Bundles of routes on one line (decision 2026-10-24): the route pieces along the axes and the
pieces of a line on which the set of cables does not change. Pure geometry, shared by the wiring
drawing (lanes, length labels), the fixings (electrical/mounting.plan_fixings: the clips of a
bundle go in one line) and the 3D scene."""

from __future__ import annotations

import itertools
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from floorplan_engine.model.geometry import Vec

_TOL = 1.0  # model mm: points on one line


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
