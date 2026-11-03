from __future__ import annotations

import math

import pytest

from floorplan_engine.model.geometry import (
    Contour,
    Vec,
    WallSegment,
    _line_intersection,
    _segments_intersect,
    _unit,
    closure_suspects,
    expected_angle_sum,
    outer_corners,
    point_in_polygon,
    signed_area,
    trace_contour,
)
from tests.conftest import make_plan

RECT = [{"length": 3200}, {"length": 4100}, {"length": 3200}, {"length": 4100}]
# L-shaped: 4000 x 3000 without the top-right 1500 x 1000 corner
L_SHAPE = [
    {"length": 3000},  # 0: up
    {"length": 2500},  # 1: right
    {"length": 1000, "turn": 270},  # 2: down, then a reflex corner
    {"length": 1500},  # 3: right
    {"length": 2000},  # 4: down
    {"length": 4000},  # 5: left
]


def test_rectangle_closed_and_area() -> None:
    plan = make_plan(RECT)
    c = trace_contour(plan.rooms[0], plan.default_wall_thickness)
    assert c.is_closed()
    assert c.closure_error == pytest.approx(0, abs=1e-6)
    assert c.area_m2 == pytest.approx(3.2 * 4.1)
    assert c.perimeter == pytest.approx(14600)


def test_first_wall_goes_up_clockwise() -> None:
    plan = make_plan(RECT)
    c = trace_contour(plan.rooms[0], 120)
    assert c.segments[0].end == Vec(0, 3200)
    assert c.segments[1].end == Vec(4100, 3200)
    # wall 0 goes up, outward is left (−X)
    assert c.segments[0].outward == Vec(-1, 0)


def test_l_shape_270_closed_and_area() -> None:
    plan = make_plan(L_SHAPE)
    c = trace_contour(plan.rooms[0], 120)
    assert c.is_closed()
    assert c.area_m2 == pytest.approx(4.0 * 3.0 - 1.5 * 1.0)
    assert point_in_polygon(Vec(1000, 1000), c.vertices)
    assert not point_in_polygon(Vec(3500, 2800), c.vertices)  # the cut-out corner


def test_unclosed_suspects_point_to_parallel_walls() -> None:
    walls = [{"length": 3200}, {"length": 4100}, {"length": 3100}, {"length": 4100}]
    plan = make_plan(walls)
    c = trace_contour(plan.rooms[0], 120)
    assert not c.is_closed()
    assert c.gap.x == pytest.approx(0, abs=1e-6)
    assert c.gap.y == pytest.approx(100)
    fixes = {s.wall: s.fixed_length for s in closure_suspects(c)}
    assert fixes == {"w1": 3100, "w3": 3200}


def test_outer_corners_respect_thickness() -> None:
    walls = [
        {"length": 3000},
        {"length": 4000},
        {"length": 3000},
        {"length": 4000, "thickness": 200},
    ]
    plan = make_plan(walls)
    c = trace_contour(plan.rooms[0], 120)
    corners = outer_corners(c)
    assert corners[0] == Vec(-120, -200)  # joint of the bottom (200) and left (120) walls
    assert corners[1] == Vec(-120, 3120)
    assert corners[2] == Vec(4120, 3120)


SQUARE_CCW = [Vec(0, 0), Vec(10, 0), Vec(10, 10), Vec(0, 10)]


def _contour(points: list[Vec], close: bool = True) -> Contour:
    """Outline from vertices: wall i goes from points[i] to points[i + 1]."""
    ends = [*points[1:], points[0]] if close else points[1:]
    segs = []
    for i, (a, b) in enumerate(zip(points, ends, strict=False)):
        d = b - a
        n = d.length()
        segs.append(WallSegment(i, f"w{i + 1}", a, b, d * (1 / n), n, 100.0, False))
    gap = segs[-1].end - points[0]
    return Contour(tuple(segs), gap, 0.0)


def test_vec_arithmetic() -> None:
    a, b = Vec(1, 2), Vec(3, -4)
    assert a + b == Vec(4, -2)
    assert a - b == Vec(-2, 6)
    assert a * 2 == Vec(2, 4)
    assert a.dot(b) == -5
    assert a.cross(b) == -10
    assert a.as_tuple() == (1, 2)


def test_vec_length_and_left_normal() -> None:
    assert Vec(3, 4).length() == 5
    assert Vec(0, 0).length() == 0
    assert Vec(1, 0).left() == Vec(0, 1)
    assert Vec(0, 1).left() == Vec(-1, 0)


@pytest.mark.parametrize(
    ("angle", "expected"),
    [(0, Vec(1, 0)), (90, Vec(0, 1)), (180, Vec(-1, 0)), (-90, Vec(0, -1)), (270, Vec(0, -1))],
)
def test_unit_axis_directions_have_no_noise(angle: float, expected: Vec) -> None:
    assert _unit(angle) == expected


@pytest.mark.parametrize(("n", "total"), [(3, 180), (4, 360), (6, 720)])
def test_expected_angle_sum(n: int, total: float) -> None:
    assert expected_angle_sum(n) == total


def test_signed_area_sign_follows_direction() -> None:
    assert signed_area(SQUARE_CCW) == 100
    assert signed_area(list(reversed(SQUARE_CCW))) == -100


@pytest.mark.parametrize("points", [[], [Vec(1, 1)], [Vec(0, 0), Vec(5, 5)]])
def test_signed_area_degenerate_is_zero(points: list[Vec]) -> None:
    assert signed_area(points) == 0


@pytest.mark.parametrize(
    ("point", "inside"),
    [
        (Vec(5, 5), True),
        (Vec(0, 0), True),  # vertex
        (Vec(10, 5), True),  # on an edge
        (Vec(5, 10), True),  # on the top edge
        (Vec(10.1, 5), False),
        (Vec(-0.1, 5), False),
        (Vec(5, 11), False),
    ],
)
def test_point_in_polygon_boundary_counts_inside(point: Vec, inside: bool) -> None:
    assert point_in_polygon(point, SQUARE_CCW) is inside


def test_segments_intersect_proper_crossing() -> None:
    assert _segments_intersect(Vec(0, 0), Vec(10, 10), Vec(0, 10), Vec(10, 0))


@pytest.mark.parametrize(
    ("q1", "q2"),
    [
        (Vec(10, 10), Vec(20, 0)),  # touching at an end
        (Vec(0, 1), Vec(10, 11)),  # parallel
        (Vec(20, 20), Vec(30, 30)),  # collinear, not overlapping
        (Vec(5, 5), Vec(5, 20)),  # end on the segment
    ],
)
def test_segments_intersect_ignores_touching_and_parallel(q1: Vec, q2: Vec) -> None:
    assert not _segments_intersect(Vec(0, 0), Vec(10, 10), q1, q2)


def test_line_intersection_and_parallel() -> None:
    hit = _line_intersection(Vec(0, 5), Vec(1, 0), Vec(3, 0), Vec(0, 1))
    assert hit == Vec(3, 5)
    assert _line_intersection(Vec(0, 0), Vec(1, 0), Vec(0, 1), Vec(2, 0)) is None


def test_contour_properties_of_closed_rectangle() -> None:
    c = _contour([Vec(0, 0), Vec(0, 3000), Vec(4000, 3000), Vec(4000, 0)])
    assert c.vertices == [Vec(0, 0), Vec(0, 3000), Vec(4000, 3000), Vec(4000, 0)]
    assert c.perimeter == 14000
    assert c.area_mm2 == 12_000_000
    assert c.area_m2 == 12
    assert c.closure_error == 0
    assert c.is_closed()
    assert c.segment("w3").start == Vec(4000, 3000)


@pytest.mark.parametrize(("gap", "closed"), [(10.0, True), (10.5, False)])
def test_is_closed_tolerance_is_inclusive(gap: float, closed: bool) -> None:
    c = Contour((), Vec(gap, 0), 0.0)
    assert c.is_closed() is closed


@pytest.mark.parametrize(("angle_err", "closed"), [(0.01, True), (0.02, False)])
def test_is_closed_checks_angle_sum(angle_err: float, closed: bool) -> None:
    assert Contour((), Vec(0, 0), angle_err).is_closed() is closed


def test_closure_suspects_empty_when_closed() -> None:
    c = _contour([Vec(0, 0), Vec(0, 3000), Vec(4000, 3000), Vec(4000, 0)])
    assert closure_suspects(c) == []


def test_closure_suspects_fix_parallel_walls() -> None:
    # the bottom wall is 100 shorter: the end is (100, 0), closure error along X
    c = _contour([Vec(0, 0), Vec(0, 3000), Vec(4000, 3000), Vec(4000, 0), Vec(100, 0)], close=False)
    suspects = {s.wall: s.fixed_length for s in closure_suspects(c)}
    assert suspects == {"w2": 3900.0, "w4": 4000.0}


def test_wall_segment_normals_and_point_at() -> None:
    seg = WallSegment(0, "w1", Vec(0, 0), Vec(0, 3000), Vec(0, 1), 3000, 120, False)
    assert seg.outward == Vec(-1, 0)
    assert seg.inward == Vec(1, 0)
    assert seg.point_at(500) == Vec(0, 500)
    assert math.isclose(seg.angle_deg, 90)
