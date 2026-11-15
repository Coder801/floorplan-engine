from __future__ import annotations

import itertools
import math

import pytest
from shapely.geometry import LineString, Point, box

from floorplan_engine.electrical.heating_layout import (
    Arc,
    Serpentine,
    Straight,
    long_side_first,
    rows_of,
    serpentine,
)
from floorplan_engine.model.geometry import Vec


def _continuous(s: Serpentine) -> None:
    for a, b in zip(s.pieces, s.pieces[1:], strict=False):
        assert (b.a - a.b).length() < 1e-6


def _inside(s: Serpentine, region: object) -> None:
    area = region.buffer(1e-3)  # type: ignore[attr-defined]
    for p in s.pieces:
        if isinstance(p, Straight):
            assert area.covers(LineString([p.a.as_tuple(), p.b.as_tuple()]))
        else:
            for k in range(9):
                assert area.covers(Point(p.at(p.start_deg + p.sweep_deg * k / 8).as_tuple()))


def test_rows_are_centred_at_the_pitch() -> None:
    rows = rows_of((0.0, 1000.0), 150.0)
    assert len(rows) == 6
    assert rows[1] - rows[0] == pytest.approx(150.0)
    assert rows[0] - 0.0 == pytest.approx(1000.0 - rows[-1])  # equal margins
    assert rows_of((0.0, 100.0), 150.0) == [50.0]  # narrower than a pitch: one row in the middle


def test_rectangle_is_one_serpentine_with_half_circle_turns() -> None:
    region = box(100, 100, 3900, 2900)
    s = serpentine(region, 150.0, True, Vec(0, 0))
    assert s is not None and s.cells == s.covered == 1
    _continuous(s)
    _inside(s, region)
    runs = [p for p in s.pieces if isinstance(p, Straight)]
    turns = [p for p in s.pieces if isinstance(p, Arc)]
    assert len(runs) == len(turns) + 1 == 18
    assert all(abs(r.a.y - r.b.y) < 1e-9 for r in runs)  # parallel to X
    assert all(t.radius == pytest.approx(75.0) and abs(t.sweep_deg) == 180 for t in turns)
    ys = sorted({round(r.a.y, 6) for r in runs})
    assert all(b - a == pytest.approx(150.0) for a, b in itertools.pairwise(ys))
    assert s.start == Vec(100.0, ys[0])  # nearest the corner it was asked for
    assert s.length == pytest.approx(sum(r.length for r in runs) + 17 * math.pi * 75)


def test_l_shape_is_one_line_through_both_arms() -> None:
    region = box(100, 100, 3900, 1400).union(box(100, 100, 1400, 2900))
    for along_x in (True, False):
        s = serpentine(region, 150.0, along_x)
        assert s is not None and s.covered == s.cells
        _continuous(s)
        _inside(s, region)


def test_u_shape_runs_across_the_arms_and_a_hole_is_reported() -> None:
    u = box(100, 100, 3900, 2900).difference(box(1500, 1500, 2500, 3000))
    across = serpentine(u, 150.0, True)
    along = serpentine(u, 150.0, False)
    assert across is not None and across.covered < across.cells  # rows split by the notch
    assert along is not None and along.covered == along.cells == 1
    _inside(along, u)
    ring = box(100, 100, 3900, 2900).difference(box(1500, 1000, 2500, 2000))
    s = serpentine(ring, 150.0, True)
    assert s is not None and s.covered < s.cells  # one line cannot go round a hole


def test_truncated_route_is_exactly_the_cable() -> None:
    s = serpentine(box(0, 0, 2000, 1500), 140.0, True)
    assert s is not None
    cut = s.truncated(7_777.0)
    assert cut.length == pytest.approx(7_777.0)
    _continuous(cut)
    assert s.truncated(s.length + 1000).length == pytest.approx(s.length)  # longer: as is


def test_vertical_runs_and_the_start_direction() -> None:
    region = box(0, 0, 1000, 3000)
    assert long_side_first(region) == (False, True)
    s = serpentine(region, 150.0, False, Vec(500, 0))
    assert s is not None and not s.along_x
    runs = [p for p in s.pieces if isinstance(p, Straight)]
    assert all(abs(r.a.x - r.b.x) < 1e-9 for r in runs)
    assert s.start.y == 0.0 and s.start_out == Vec(0.0, -1.0)
    assert serpentine(box(0, 0, 1, 1).difference(box(0, 0, 1, 1)), 150.0, True) is None


def test_same_region_same_cable() -> None:
    region = box(100, 100, 3900, 1400).union(box(100, 100, 1400, 2900))
    a = serpentine(region, 133.0, True, Vec(4000, 0))
    b = serpentine(region, 133.0, True, Vec(4000, 0))
    assert a == b
