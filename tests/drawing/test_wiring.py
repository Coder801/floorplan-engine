"""Wiring sheet: route pieces along axes and small formatters, without DXF."""

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
        [Vec(0, 0), Vec(1, 0)],  # no longer than the 1 mm tolerance
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
        (Vec(-1, 1), Vec(1, -1)),  # left-up → right-down
        (Vec(1, -1), Vec(1, -1)),
        (Vec(1e-12, -1), Vec(-1e-12, 1)),  # almost vertical down: vertical within tolerance
    ],
)
def test_readable_reads_left_to_right_or_bottom_up(direction: Vec, expected: Vec) -> None:
    assert _readable(direction) == expected


@pytest.mark.parametrize(
    ("mm", "text"), [(0, "0,0"), (1000, "1,0"), (1260, "1,3"), (12340, "12,3"), (49, "0,0")]
)
def test_m_meters_with_comma(mm: float, text: str) -> None:
    assert _m(mm) == text


@pytest.mark.parametrize("along", [Vec(1, 0), Vec(0, 1)])
def test_label_box_covers_the_real_text_with_descender(along: Vec) -> None:
    """A label's reserved box is the drawn text's extents, descender included: two labels the
    placer puts side by side never overlap on the sheet."""
    from ezdxf import bbox
    from ezdxf.filemanagement import new

    from floorplan_engine.drawing.plan import add_text
    from floorplan_engine.drawing.wiring import LENGTH_MM, _Labels

    labels = _Labels([])
    center = Vec(1000, 1000)
    text = "↑h1,0"
    rect = labels._rect(text, center, along)
    msp = new().modelspace()
    add_text(msp, text, center, LENGTH_MM, "0", math.degrees(math.atan2(along.y, along.x)))
    ext = bbox.extents(msp.query("TEXT"))
    tol = 1e-6
    x0, y0, x1, y1 = rect.bounds
    assert x0 <= ext.extmin.x + tol and y0 <= ext.extmin.y + tol
    assert x1 >= ext.extmax.x - tol and y1 >= ext.extmax.y - tol
