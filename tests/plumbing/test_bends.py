from __future__ import annotations

import itertools

import pytest

from floorplan_engine.model.geometry import Vec
from floorplan_engine.plumbing.bends import (
    bends,
    chamfer,
    is_octilinear,
    octilinear,
    simplify,
    tee45,
    turn,
)


def turns(path: list[Vec]) -> list[float]:
    return [turn(b - a, c - b) for a, b, c in zip(path, path[1:], path[2:], strict=False)]


def test_octilinear_splits_odd_segment() -> None:
    out = octilinear([Vec(0, 0), Vec(300, 100)])
    assert out == [Vec(0, 0), Vec(200, 0), Vec(300, 100)]
    assert all(is_octilinear(b - a) for a, b in itertools.pairwise(out))


def test_chamfer_right_angle_into_two_bends() -> None:
    out = chamfer([Vec(0, 0), Vec(1000, 0), Vec(1000, 1000)])
    assert out[0] == Vec(0, 0) and out[-1] == Vec(1000, 1000)  # концы на месте
    assert turns(out) == pytest.approx([45.0, 45.0])
    assert bends(out) == 2


def test_chamfer_135_into_three_bends() -> None:
    out = chamfer([Vec(0, 0), Vec(1000, 0), Vec(0, 1000)])
    assert turns(out) == pytest.approx([45.0, 45.0, 45.0])
    assert bends(out) == 3


def test_chamfer_shrinks_on_short_segments() -> None:
    out = chamfer([Vec(0, 0), Vec(1000, 0), Vec(1000, 40), Vec(2000, 40)])
    assert turns(out) == pytest.approx([45.0, 45.0])  # уступ 40 мм — одна диагональ
    assert bends(out) == 2
    assert all((b - a).length() > 0 for a, b in itertools.pairwise(out))


def test_bends_counts_45_per_step() -> None:
    assert bends([Vec(0, 0), Vec(100, 0), Vec(100, 100)]) == 2
    assert bends([Vec(0, 0), Vec(100, 0), Vec(200, 100)]) == 1
    assert bends([Vec(0, 0), Vec(100, 0), Vec(200, 0)]) == 0


def test_simplify_drops_collinear_diagonal() -> None:
    assert simplify([Vec(0, 0), Vec(100, 100), Vec(200, 200)]) == [Vec(0, 0), Vec(200, 200)]


def test_tee45_branch_enters_along_flow() -> None:
    parent = [Vec(0, 0), Vec(2000, 0)]  # от стояка (0, 0): течёт к началу, влево
    branch = [Vec(1000, 0), Vec(1000, 800)]  # врезка под 90°
    out, along = tee45(branch, parent, 1000.0)
    assert along == pytest.approx(900.0)  # место врезки сдвинулось к стояку
    assert out[0] == Vec(900, 0)
    flow_in = out[0] - out[1]  # течение отвода у врезки
    assert turn(flow_in, Vec(-1, 0)) == pytest.approx(45.0)
    assert out[-1] == Vec(1000, 800)


def test_tee45_keeps_branch_already_at_45() -> None:
    parent = [Vec(0, 0), Vec(2000, 0)]
    branch = [Vec(1000, 0), Vec(1500, 500)]
    out, along = tee45(branch, parent, 1000.0)
    assert out == branch and along == 1000.0
