"""Сантехприборы контуром на плане: у каждого вида свой рисунок, у стены и в помещение."""

from __future__ import annotations

import pytest

from floorplan_engine.drawing.fixture_symbols import SIZES, Frame, symbol
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.plumbing import FixtureType


@pytest.mark.parametrize("kind", list(FixtureType))
def test_symbol_stays_in_its_place_at_wall(kind: FixtureType) -> None:
    # Стена — ось x, помещение — вверх; прибор с серединой подводки в x = 1000
    frame = Frame(Vec(1000.0, 0.0), Vec(1.0, 0.0), Vec(0.0, 1.0))
    shapes = symbol(kind, frame)
    assert shapes and all(len(s.points) >= 2 for s in shapes)
    w, d = SIZES[kind]
    for s in shapes:
        for v in s.points:
            assert -0.5 <= v.y <= d + 0.5  # от стены в помещение, не глубже типового
            assert abs(v.x - 1000.0) <= w / 2 + 0.5


def test_bath_in_obstacle_size() -> None:
    frame = Frame(Vec(0.0, 0.0), Vec(1.0, 0.0), Vec(0.0, 1.0))
    outer = symbol(FixtureType.BATH, frame, (1500.0, 700.0))[0]
    xs = [v.x for v in outer.points]
    ys = [v.y for v in outer.points]
    assert max(xs) - min(xs) == pytest.approx(1500.0, abs=1.0)
    assert max(ys) - min(ys) == pytest.approx(700.0, abs=1.0)
