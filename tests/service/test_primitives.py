"""Примитивы страницы: отрезок (длина, направление, близость точки) и надпись (число, точка)."""

from __future__ import annotations

import pytest

from floorplan_engine.service.facts.primitives import Direction, Label, Segment


def test_segment_length() -> None:
    assert Segment(0, 0, 3, 4).length == 5
    assert Segment(2, 2, 2, 2).length == 0


@pytest.mark.parametrize(
    ("seg", "direction"),
    [
        (Segment(0, 0, 10, 0), "h"),
        (Segment(10, 5, 0, 5.19), "h"),  # перекос меньше 0.2
        (Segment(0, 0, 0, 10), "v"),
        (Segment(3, 10, 3.1, 0), "v"),
        (Segment(0, 0, 10, 10), None),
        (Segment(0, 0, 10, 0.2), None),  # перекос ровно 0.2 — уже не горизонталь
        (Segment(0, 0, 0.1, 0.1), None),  # короче 0.2 в обе стороны
        (Segment(0, 0, 0.2, 0), "h"),  # длина ровно 0.2 — ещё отрезок
        (Segment(1, 1, 1, 1), None),
    ],
)
def test_segment_direction(seg: Segment, direction: Direction | None) -> None:
    assert seg.direction == direction


@pytest.mark.parametrize(
    ("x", "y", "near"),
    [
        (5, 0, True),
        (5, 1, True),  # ровно на допуске
        (5, 1.01, False),
        (0, 0, True),
        (11, 0, True),  # за концом, но в пределах допуска
        (11.5, 0, False),
        (-0.6, 0.6, True),  # у начала по диагонали: √0.72 < 1
        (-0.8, 0.8, False),
    ],
)
def test_segment_passes_near(x: float, y: float, near: bool) -> None:
    assert Segment(0, 0, 10, 0).passes_near(x, y, 1.0) is near


def test_segment_passes_near_zero_length_uses_box() -> None:
    dot = Segment(5, 5, 5, 5)
    assert dot.passes_near(5.9, 4.1, 1.0)
    assert not dot.passes_near(6.1, 5, 1.0)


def _label(text: str, direction: Direction = "h") -> Label:
    return Label(text, direction, a0=100, a1=140, base=50, perp=55, height=10)


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("1200", 1200),
        ("1 200", 1200),
        ("12 345 678", 12345678),
        ("0", 0),
        ("12 34", None),
        ("1 2000", None),
        ("1200 мм", None),
        ("", None),
        ("-300", None),
        ("2,5", None),
    ],
)
def test_label_number(text: str, number: int | None) -> None:
    assert _label(text).number == number


def test_label_mid_and_point_horizontal() -> None:
    lab = _label("100")
    assert lab.mid == 120
    assert lab.point() == (120, 55)


def test_label_point_vertical_swaps_axes() -> None:
    assert _label("100", "v").point() == (55, 120)


def test_label_default_confidence_is_vector() -> None:
    assert _label("1").confidence == 1.0
