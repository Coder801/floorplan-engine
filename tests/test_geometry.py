from __future__ import annotations

import pytest

from shtroba.geometry import (
    Vec,
    closure_suspects,
    outer_corners,
    point_in_polygon,
    trace_contour,
)
from tests.conftest import make_plan

RECT = [{"length": 3200}, {"length": 4100}, {"length": 3200}, {"length": 4100}]
# Г-образная: 4000 x 3000 без правого верхнего угла 1500 x 1000
L_SHAPE = [
    {"length": 3000},  # 0: вверх
    {"length": 2500},  # 1: вправо
    {"length": 1000, "turn": 270},  # 2: вниз, затем входящий угол
    {"length": 1500},  # 3: вправо
    {"length": 2000},  # 4: вниз
    {"length": 4000},  # 5: влево
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
    # стена 0 идёт вверх, наружу — влево (−X)
    assert c.segments[0].outward == Vec(-1, 0)


def test_l_shape_270_closed_and_area() -> None:
    plan = make_plan(L_SHAPE)
    c = trace_contour(plan.rooms[0], 120)
    assert c.is_closed()
    assert c.area_m2 == pytest.approx(4.0 * 3.0 - 1.5 * 1.0)
    assert point_in_polygon(Vec(1000, 1000), c.vertices)
    assert not point_in_polygon(Vec(3500, 2800), c.vertices)  # вырезанный угол


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
    assert corners[0] == Vec(-120, -200)  # стык нижней (200) и левой (120)
    assert corners[1] == Vec(-120, 3120)
    assert corners[2] == Vec(4120, 3120)
