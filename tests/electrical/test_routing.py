"""Route: polyline simplification and axis length; grid search (cost and pruning)."""

from __future__ import annotations

import pytest
from shapely.geometry import box

from floorplan_engine.electrical.routing import (
    APART,
    End,
    Grid,
    Router,
    apart_cells,
    beside_mm,
    length,
    simplify,
)
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
        (_v((0, 0), (300, 400)), 500),  # a slanted piece (economy) counts by the hypotenuse
        (_v((0, 0), (100, 0), (0, 0)), 200),
    ],
)
def test_length_along_segments(path: list[Vec], mm: float) -> None:
    assert length(path) == pytest.approx(mm)


def test_move_end_keeps_right_angles() -> None:
    from floorplan_engine.electrical.routing import move_end

    u = _v((0, 0), (0, 1000), (2000, 1000), (2000, 0))
    # Across the first piece: the neighbouring vertex follows, the piece stays vertical
    assert move_end(u, True, Vec(200, 0)) == _v((200, 0), (200, 1000), (2000, 1000), (2000, 0))
    # A single-piece route gets a bend
    assert move_end(_v((0, 0), (1000, 0)), False, Vec(1000, 300)) == _v(
        (0, 0), (0, 300), (1000, 300)
    )


def test_fit_path_snaps_ends_to_nodes() -> None:
    from floorplan_engine.electrical.routing import fit_path

    path = _v((0, 0), (0, 1000), (2000, 1000))
    assert fit_path(path, Vec(0.3, 0), Vec(2000, 1000)) == _v((0.3, 0), (0, 1000), (2000, 1000))
    assert fit_path(path, Vec(0, 0), Vec(2000, 1500)) == _v((0, 0), (0, 1500), (2000, 1500))


def test_penalty_makes_path_go_around() -> None:
    """An extra cell cost (plumbing: a partition) makes the path go around; without it, straight
    through.
    """
    from shapely.geometry import box as rect

    from floorplan_engine.electrical.routing import STEP, Grid
    from floorplan_engine.model.geometry import Vec

    grid = Grid.of(rect(0, 0, 3000, 1500))
    start = grid.nearest_free(Vec(400, 400))
    goal = grid.nearest_free(Vec(2600, 400))
    prev, dist = grid.search(start)
    straight = grid.path(prev, dist, goal)
    assert all(abs(p.y - straight[0].y) < 1e-6 for p in straight)
    wall = {
        k
        for k in range(len(grid.free))
        if abs(grid.center(k).x - 1500) < STEP and grid.center(k).y < 1000
    }
    grid.penalty = dict.fromkeys(wall, 10_000.0)
    prev, dist = grid.search(start)
    around = grid.path(prev, dist, goal)
    assert max(p.y for p in around) > 1000


def _square_grid() -> Grid:
    return Grid.of(box(0, 0, 3000, 3000))


def test_search45_mult_makes_open_cells_expensive() -> None:
    """Step cost × the cell's mult: the middle costs more, so the path goes around the edge, not
    the diagonal.
    """
    grid = _square_grid()
    start = grid.nearest_free(Vec(200, 200))
    goal = grid.nearest_free(Vec(2800, 2800))
    _, plain = grid.search45(start)
    cheap = min(plain[goal * 8 + d] for d in range(8) if goal * 8 + d in plain)
    edge = {k for k in range(len(grid.free)) if min(grid.center(k).x, grid.center(k).y) < 300}
    edge |= {k for k in range(len(grid.free)) if max(grid.center(k).x, grid.center(k).y) > 2700}
    grid.mult = [1.0 if k in edge else 4.0 for k in range(len(grid.free))]
    prev, dist = grid.search45(start)
    path = grid.path(prev, dist, goal, ndirs=8)
    assert all(min(v.x, v.y) < 300 or max(v.x, v.y) > 2700 for v in path)
    assert min(dist[goal * 8 + d] for d in range(8) if goal * 8 + d in dist) > cheap


def test_search45_prune_by_length_from_start() -> None:
    """prune(cell, length from start): beyond 1 m from the start, the middle is unavailable."""
    grid = _square_grid()
    start = grid.nearest_free(Vec(200, 200))

    def prune(cell: int, length: float) -> bool:
        c = grid.center(cell)
        middle = 500 < c.x < 2500 and 500 < c.y < 2500
        return middle and length > 1000

    _, dist = grid.search45(start, prune=prune, start_len=100.0)
    reached = {s // 8 for s in dist}
    far = grid.nearest_free(Vec(1500, 1500))  # ≈ 1.8 m straight: past the limit
    near = grid.nearest_free(Vec(700, 700))  # ≈ 0.7 m plus 100 to the start: within the limit
    assert far not in reached and near in reached


def test_low_voltage_route_keeps_apart_from_power_and_crosses_at_right_angle() -> None:
    """Decision 2026-11-13: beside a power cable no closer than APART, across it at 90°."""
    area = box(0, 0, 4000, 3000)
    power = _v((250, 1550), (3750, 1550))  # across the room, along x
    plain = Router(area, End(Vec(250, 1550), False))
    same = plain.route(End(Vec(3750, 1550), False))
    assert beside_mm(same, [power]) == pytest.approx(3500)  # the shortest way lies on the cable
    apart = plain.apart_from([power])
    assert apart is not plain and plain.apart_from([]) is plain
    moved = apart.route(End(Vec(3750, 1550), False))
    # only the ends, which are on the cable itself, stay close
    assert beside_mm(moved, [power]) <= 2 * APART
    assert any(abs(p.y - 1550) >= APART for p in moved)
    across = apart.route(End(Vec(250, 2750), False))  # straight across the power cable
    assert length(across) == pytest.approx(1200) and beside_mm(across, [power]) == 0
    assert (
        Router(area, End(Vec(250, 1550), False), any_angle=True).apart_from([power]).grid.apart
        is None
    )


def test_apart_cells_by_direction() -> None:
    grid = Grid.of(box(0, 0, 2000, 2000))
    along_x, along_y = apart_cells(grid, [_v((250, 1050), (1550, 1050), (1550, 250))])
    ys = {grid.center(k).y for k in along_x}
    assert ys == {950.0, 1050.0, 1150.0}  # the row of the cable and one row each side
    xs = {grid.center(k).x for k in along_y}
    assert xs == {1450.0, 1550.0, 1650.0}
    assert apart_cells(grid, [_v((250, 250), (1750, 1750))]) == (frozenset(), frozenset())


def test_beside_mm_counts_overlap_once() -> None:
    path = _v((0, 100), (1000, 100))
    others = [_v((0, 0), (600, 0)), _v((400, 200), (800, 200)), _v((900, 300), (1000, 300))]
    assert beside_mm(path, others) == pytest.approx(800)  # 0–600 and 400–800 overlap; 300 is far
    assert beside_mm(_v((500, -500), (500, 500)), others) == 0  # across
