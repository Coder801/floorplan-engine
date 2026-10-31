"""Лист проводки: участки трасс по осям и мелкие форматтеры — без DXF."""

from __future__ import annotations

import math

import pytest

from floorplan_engine.drawing.wiring import Bundle, Segment, _m, _readable, _unit, segments
from floorplan_engine.model.geometry import Vec


def test_segments_axis_and_order_of_ends() -> None:
    path = [Vec(500, 0), Vec(100, 0), Vec(100, 300)]
    assert segments([path]) == [
        Segment(0, 0, "h", 0, 100, 500),
        Segment(0, 1, "v", 100, 0, 300),
    ]


def test_segments_number_runs_and_skip_diagonals() -> None:
    paths = [[Vec(0, 0), Vec(100, 100)], [Vec(0, 0), Vec(0, 50), Vec(80, 50)]]
    assert segments(paths) == [
        Segment(1, 0, "v", 0, 0, 50),
        Segment(1, 1, "h", 50, 0, 80),
    ]


@pytest.mark.parametrize(
    "path",
    [
        [],
        [Vec(0, 0)],
        [Vec(0, 0), Vec(0, 0)],
        [Vec(0, 0), Vec(1, 0)],  # не длиннее допуска 1 мм
        [Vec(0, 0), Vec(0, 0.5)],
    ],
)
def test_segments_ignore_points_and_tiny_steps(path: list[Vec]) -> None:
    assert segments([path]) == []


def test_segments_fixed_coordinate_is_rounded() -> None:
    (seg,) = segments([[Vec(0, 99.6), Vec(200, 100.4)]])
    assert seg.axis == "h" and seg.fixed == 100


def test_bundle_length() -> None:
    assert Bundle("h", 0, 150, 900, (0, 1), (0.0, 30.0)).length == 750


def test_unit_vector() -> None:
    u = _unit(Vec(3, 4))
    assert u.as_tuple() == pytest.approx((0.6, 0.8))
    assert math.isclose(_unit(Vec(0, -250)).length(), 1)


@pytest.mark.parametrize(
    ("direction", "expected"),
    [
        (Vec(1, 0), Vec(1, 0)),
        (Vec(-1, 0), Vec(1, 0)),
        (Vec(0, 1), Vec(0, 1)),
        (Vec(0, -1), Vec(0, 1)),
        (Vec(-1, 1), Vec(1, -1)),  # влево-вверх → вправо-вниз
        (Vec(1, -1), Vec(1, -1)),
        (Vec(1e-12, -1), Vec(-1e-12, 1)),  # почти вертикаль вниз — по допуску вертикаль
    ],
)
def test_readable_reads_left_to_right_or_bottom_up(direction: Vec, expected: Vec) -> None:
    assert _readable(direction) == expected


@pytest.mark.parametrize(
    ("mm", "text"), [(0, "0,0"), (1000, "1,0"), (1260, "1,3"), (12340, "12,3"), (49, "0,0")]
)
def test_m_meters_with_comma(mm: float, text: str) -> None:
    assert _m(mm) == text
