"""Трасса: упрощение ломаной и длина по осям — без сетки и плана."""

from __future__ import annotations

import pytest

from floorplan_engine.electrical.routing import length, simplify
from floorplan_engine.model.geometry import Vec


def _v(*pts: tuple[float, float]) -> list[Vec]:
    return [Vec(x, y) for x, y in pts]


@pytest.mark.parametrize("path", [[], _v((1, 2))])
def test_simplify_short_paths_unchanged(path: list[Vec]) -> None:
    assert simplify(path) == path


def test_simplify_drops_repeated_points() -> None:
    assert simplify(_v((0, 0), (0, 0), (100, 0), (100, 0))) == _v((0, 0), (100, 0))


def test_simplify_drops_points_on_straight_line() -> None:
    path = _v((0, 0), (100, 0), (200, 0), (200, 100), (200, 300))
    assert simplify(path) == _v((0, 0), (200, 0), (200, 300))


def test_simplify_keeps_corners() -> None:
    path = _v((0, 0), (100, 0), (100, 100), (200, 100))
    assert simplify(path) == path


def test_simplify_tolerates_float_noise() -> None:
    path = _v((0, 0), (100, 1e-9), (200, 0))
    assert simplify(path) == _v((0, 0), (200, 0))


def test_simplify_keeps_diagonal_points() -> None:
    path = _v((0, 0), (100, 100), (200, 200))
    assert simplify(path) == path


@pytest.mark.parametrize(
    ("path", "mm"),
    [
        ([], 0),
        (_v((5, 5)), 0),
        (_v((0, 0), (300, 0)), 300),
        (_v((0, 0), (300, 0), (300, -200)), 500),
        (_v((0, 0), (300, 400)), 700),  # по осям, не по гипотенузе
        (_v((0, 0), (100, 0), (0, 0)), 200),
    ],
)
def test_length_is_manhattan(path: list[Vec], mm: float) -> None:
    assert length(path) == mm


def test_move_end_keeps_right_angles() -> None:
    from floorplan_engine.electrical.routing import move_end

    u = _v((0, 0), (0, 1000), (2000, 1000), (2000, 0))
    # Поперёк первого участка: соседняя вершина едет следом, участок остаётся вертикальным
    assert move_end(u, True, Vec(200, 0)) == _v((200, 0), (200, 1000), (2000, 1000), (2000, 0))
    # Трасса из одного участка получает излом
    assert move_end(_v((0, 0), (1000, 0)), False, Vec(1000, 300)) == _v(
        (0, 0), (0, 300), (1000, 300)
    )


def test_fit_path_snaps_ends_to_nodes() -> None:
    from floorplan_engine.electrical.routing import fit_path

    path = _v((0, 0), (0, 1000), (2000, 1000))
    assert fit_path(path, Vec(0.3, 0), Vec(2000, 1000)) == _v((0.3, 0), (0, 1000), (2000, 1000))
    assert fit_path(path, Vec(0, 0), Vec(2000, 1500)) == _v((0, 0), (0, 1500), (2000, 1500))
