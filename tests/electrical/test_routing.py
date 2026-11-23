"""Route: polyline simplification and axis length; grid search (cost and pruning); the jog at a
route's end slid back; openings and ready holes as bands (decision 2026-11-23); the search memo
of a build."""

from __future__ import annotations

import itertools
import math

import pytest
import shapely
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry

from floorplan_engine.electrical.routing import (
    APART,
    HOLE_CELL_COST,
    PANEL_FREE,
    PASS_FAVOUR,
    STEP,
    WALL_HOLE_SHARE,
    WALL_PASS_COST,
    End,
    Grid,
    Router,
    apart_cells,
    below_ceiling,
    beside_mm,
    ceiling_passes,
    crossings,
    length,
    search_memo,
    simplify,
    slide_jog,
)
from floorplan_engine.model.geometry import Vec
from tests.conftest import make_plan


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


def test_slide_jog_removes_a_jog_to_a_point_off_the_cell_centres() -> None:
    """A socket at x=3965 by the 3950 column: the route drops on the point's own line."""
    grid = Grid.of(box(0, 0, 5000, 3000))
    path = _v((300, 2650), (3950, 2650), (3950, 250), (3965, 250), (3965, 60))
    assert slide_jog(path, grid) == _v((300, 2650), (3965, 2650), (3965, 60))


def test_slide_jog_moves_the_jog_to_the_farthest_clear_spot() -> None:
    """A wall end within CLEARANCE of the point's line: the jog goes right past it, not at the
    wall the point is on."""
    room = box(0, 0, 5000, 3000).difference(box(1500, 2350, 2450, 2450))
    grid = Grid.of(room)
    path = _v((300, 2650), (2650, 2650), (2650, 250), (2450, 250), (2450, 60))
    assert slide_jog(path, grid) == _v(
        (300, 2650), (2650, 2650), (2650, 2150), (2450, 2150), (2450, 60)
    )


def test_slide_jog_keeps_a_long_piece_and_the_start() -> None:
    """A piece longer than JOG_MAX at the end is a run of its own; the start is not touched."""
    grid = Grid.of(box(0, 0, 5000, 3000))
    long_end = _v((300, 2650), (1000, 2650), (1000, 250), (1500, 250), (1500, 60))
    assert slide_jog(long_end, grid) == long_end
    jog_at_start = _v((1500, 60), (1500, 250), (1000, 250), (1000, 2650), (300, 2650))
    assert slide_jog(jog_at_start, grid) == jog_at_start


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


def test_apart_cells_skip_the_panel_zone() -> None:
    """Decision 2026-11-18: within PANEL_FREE of the panel a low-voltage cable need not keep
    APART from power: all cables leave the panel together."""
    grid = Grid.of(box(0, 0, 2000, 2000))
    power = [_v((250, 1050), (1750, 1050))]
    panel = Vec(250, 1050)
    along_x, _ = apart_cells(grid, power, panel)
    every = apart_cells(grid, power)[0]
    near = {k for k in every if (grid.center(k) - panel).length() < PANEL_FREE}
    assert near and not near & along_x
    assert min((grid.center(k) - panel).length() for k in along_x) >= PANEL_FREE


def test_beside_mm_counts_overlap_once() -> None:
    path = _v((0, 100), (1000, 100))
    others = [_v((0, 0), (600, 0)), _v((400, 200), (800, 200)), _v((900, 300), (1000, 300))]
    assert beside_mm(path, others) == pytest.approx(800)  # 0–600 and 400–800 overlap; 300 is far
    assert beside_mm(_v((500, -500), (500, 500)), others) == 0  # across


def test_search_memo_shares_searches_with_the_same_inputs() -> None:
    area, source = box(0, 0, 3000, 2000), End(Vec(250, 1550), False)
    target = End(Vec(2800, 300), False)
    with search_memo():
        a, b = Router(area, source), Router(area, source)
        other = Router(area, source, any_angle=True)
        with search_memo():  # a nested block uses the outer memo
            c = Router(area, source)
    assert a.dist is b.dist is c.dist
    assert other.dist is not a.dist
    assert a.route(target) == Router(area, source).route(target)


def test_search_memo_forgets_after_the_block() -> None:
    area, source = box(0, 0, 3000, 2000), End(Vec(250, 1550), False)
    with search_memo():
        inside = Router(area, source)
    assert Router(area, source).dist is not inside.dist
    assert Router(area, source).dist is not Router(area, source).dist


def test_route_is_traced_only_while_recording() -> None:
    """Router.route gives the same path with and without recording; recording keeps the search:
    the grid path, the final route and its cost."""
    from floorplan_engine.electrical import trace
    from floorplan_engine.electrical.routing import RouteTrace

    router = Router(box(0, 0, 3000, 2000), End(Vec(150, 150), False))
    target = End(Vec(2800, 1800), False)
    plain = router.route(target)
    with trace.recording() as events, trace.scope(line="wire_7"):
        traced = router.route(target)
    assert traced == plain
    [event] = events
    assert event.labels["line"] == "wire_7"
    found = event.payload
    assert isinstance(found, RouteTrace)
    assert list(found.path) == plain
    assert found.cost == router.cost(target.node)
    assert found.cell_cost(found.start) == 0.0
    assert found.cell_cost(found.target) == found.cost
    assert found.wall_cells == 0
    assert all(found.grid.index(c) in range(len(found.grid.free)) for c in found.cells)


def test_grid_index_inverts_center() -> None:
    grid = Grid.of(box(0, 0, 1000, 700))
    assert all(grid.index(grid.center(k)) == k for k in range(len(grid.free)))


def _two_rooms() -> tuple[BaseGeometry, list[Polygon], list[Polygon]]:
    """Rooms 0…3000 and 3100…6100 with a 100 partition at x 3000…3100 and a door at y 1200…2000:
    the free area, the drillable wall bands beside the door and the door strip, as
    free_area, drillable_walls and ceiling_passes give them."""
    door = box(3000, 1200, 3100, 2000)
    area = shapely.unary_union([box(0, 0, 3000, 3000), box(3100, 0, 6100, 3000), door])
    walls = [box(3000, 0, 3100, 1199), box(3000, 2001, 3100, 3000)]
    return area, walls, [door]


def test_opening_costs_like_a_wall_on_the_ceiling_and_is_free_on_the_floor() -> None:
    """Decision 2026-11-23: on the ceiling plane the strip of a door lower than the ceiling is a
    band that costs the pass; the floor router (no passes) crosses it for nothing."""
    area, walls, passes = _two_rooms()
    source, target = End(Vec(75, 1500), True), Vec(5000, 1500)
    floor = Router(area, source, walls=walls)
    ceiling = Router(area, source, walls=walls, passes=passes)
    assert floor.bands == tuple(walls) and ceiling.bands == (*walls, *passes)
    extra = ceiling.cost(target) - floor.cost(target)
    assert WALL_PASS_COST / 2 < extra < WALL_PASS_COST  # the band's cells across the door

    def in_door(router: Router) -> list[int]:
        return [
            k
            for k in (router.grid.penalty or {})
            if 3000 < router.grid.center(k).x < 3100 and 1200 < router.grid.center(k).y < 2000
        ]

    assert in_door(ceiling) and not in_door(floor)
    # A pass through the door and a pass through the wall cost the same, less PASS_FAVOUR
    through_wall = Router(area, End(Vec(75, 300), True), walls=walls, passes=passes).cost(
        Vec(5000, 300)
    )
    through_door = ceiling.cost(target)
    assert 0 < through_wall - through_door <= PASS_FAVOUR


def test_tie_goes_through_the_opening_not_a_new_hole() -> None:
    """A target reachable through the door and through the wall at the same length: the opening
    wins by PASS_FAVOUR."""
    area, walls, passes = _two_rooms()
    router = Router(area, End(Vec(75, 1500), True), walls=walls, passes=passes)
    path = router.route(End(Vec(6025, 500), True))
    crossed = [a.y for a, b in itertools.pairwise(path) if a.x < 3000 < 3100 < b.x]
    assert crossed and all(1200 <= y <= 2000 for y in crossed)


def test_ready_hole_makes_the_band_free_within_share() -> None:
    """A line routed before crossed the wall at y 300: the next line through the same spot pays
    HOLE_CELL_COST per cell instead of the pass; a hole farther than WALL_HOLE_SHARE changes
    nothing."""
    area, walls, passes = _two_rooms()
    source, target = End(Vec(75, 300), True), Vec(5000, 300)
    paid = Router(area, source, walls=walls, passes=passes)
    free = Router(
        area, source, walls=walls, passes=passes, holes=[(Vec(3000, 300), Vec(3100, 300))]
    )
    far = Router(area, source, walls=walls, passes=passes, holes=[(Vec(3000, 900), Vec(3100, 900))])
    saved = paid.cost(target) - free.cost(target)
    assert WALL_PASS_COST / 2 < saved < WALL_PASS_COST
    assert far.cost(target) == paid.cost(target)
    assert free.grid.opened and all(
        math.hypot(free.grid.center(k).x - 3050, free.grid.center(k).y - 300)
        < WALL_HOLE_SHARE + STEP
        for k in free.grid.opened
    )
    # Another line's hole: twice the residual of an own one (the tie-break), still no pass
    assert all(free.grid.penalty[k] == 2 * HOLE_CELL_COST for k in free.grid.opened)  # type: ignore[index]
    # A target the door and the hole reach at the same length now goes through the hole
    through_hole = free.route(End(Vec(5000, 1500), False))
    crossed = [a.y for a, b in itertools.pairwise(through_hole) if a.x < 3000 < 3100 < b.x]
    assert len(crossed) == 1 and abs(crossed[0] - 300) < STEP


def test_tie_between_two_ready_holes_goes_through_the_own_one() -> None:
    """A target as near through a hole another line made (the door) as through a hole of the same
    source (the wall): the own hole wins, so the cables of one source leave it together."""
    area, walls, passes = _two_rooms()
    # From the top wall of a to the bottom wall of b: down, across and down again, the same
    # length and turns through the hole at y 600 and the one at y 1500; a new hole would pay
    source, target = End(Vec(1500, 2925), False), End(Vec(4500, 75), False)
    wall_hole, door_hole = (Vec(3000, 600), Vec(3100, 600)), (Vec(3000, 1500), Vec(3100, 1500))
    holes = [wall_hole, door_hole]

    def crossed(router: Router) -> float:
        (y,) = [a.y for a, b in itertools.pairwise(router.route(target)) if a.x < 3000 < 3100 < b.x]
        return y

    own_wall = Router(area, source, walls=walls, passes=passes, holes=holes, own=[wall_hole])
    own_door = Router(area, source, walls=walls, passes=passes, holes=holes, own=[door_hole])
    assert abs(crossed(own_wall) - 600) <= WALL_HOLE_SHARE  # anywhere in the hole's zone
    assert abs(crossed(own_door) - 1500) <= WALL_HOLE_SHARE
    assert own_wall.own == (wall_hole,) and own_door.cost(target.node) == own_wall.cost(target.node)
    # own that is not a hole is dropped; a different own is a different search
    assert Router(area, source, walls=walls, own=[wall_hole]).own == ()
    assert own_wall.dist is not own_door.dist


def test_with_holes_and_rebased_keep_the_bands() -> None:
    area, walls, passes = _two_rooms()
    plain = Router(area, End(Vec(75, 300), True))
    assert plain.with_holes([(Vec(3000, 300), Vec(3100, 300))]) is plain  # no bands to open
    router = Router(area, End(Vec(75, 300), True), walls=walls, passes=passes)
    assert router.with_holes(()) is router
    hole = (Vec(3000, 300), Vec(3100, 300))
    opened = router.with_holes([hole], [hole])
    assert opened is not router and opened.walls == router.walls and opened.passes == router.passes
    assert opened.with_holes(opened.holes, opened.own) is opened
    assert opened.with_holes(opened.holes) is not opened  # no longer its own hole
    moved = opened.rebased(End(Vec(500, 500), False))
    assert (moved.holes, moved.own) == (opened.holes, opened.own) and moved.bands == opened.bands
    assert moved.rebased(moved.source) is moved
    apart = opened.apart_from([[Vec(0, 0), Vec(1000, 0)]])
    assert (apart.holes, apart.own) == (opened.holes, opened.own)


def test_crossings_are_the_pieces_across_the_bands() -> None:
    _, walls, passes = _two_rooms()
    path = [Vec(250, 300), Vec(5000, 300), Vec(5000, 1500), Vec(2000, 1500)]
    found = crossings(path, [*walls, *passes])
    assert [(round(a.x), round(a.y), round(b.x), round(b.y)) for a, b in found] == [
        (3000, 300, 3100, 300),
        (3100, 1500, 3000, 1500),
    ]
    assert crossings(path, []) == [] and crossings(path[:1], walls) == []


def test_below_ceiling_and_ceiling_passes() -> None:
    """A door with its top under the ceiling is a band on the ceiling; one up to the ceiling and a
    window are not; a door without a height is DOOR_TOP_MM high."""
    from floorplan_engine.model.geometry import DOOR_TOP_MM, room_geometries
    from floorplan_engine.validation.plan import validate_plan

    plan = make_plan(
        [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}],
        [
            {"wall": "w1", "type": "door", "offset": 500, "width": 900},
            {"wall": "w2", "type": "door", "offset": 500, "width": 900, "height": 2700},
            {"wall": "w3", "type": "opening", "offset": 500, "width": 1200, "height": 2200},
            {"wall": "w4", "type": "window", "offset": 500, "width": 1200, "height": 1400},
        ],
    )
    (o1, o2, o3, o4) = plan.rooms[0].openings
    ceiling = plan.ceiling_height
    assert ceiling > DOOR_TOP_MM
    assert below_ceiling(o1, ceiling) and below_ceiling(o3, ceiling)
    assert not below_ceiling(o2, ceiling) and not below_ceiling(o4, ceiling)
    _, contours = validate_plan(plan)
    geoms = list(room_geometries(plan, contours))
    strips = ceiling_passes(geoms, ceiling)
    assert len(strips) == 2
    assert not ceiling_passes(geoms, DOOR_TOP_MM)  # a ceiling at the door tops: nothing above


def test_search_memo_shares_the_base_grid_between_hole_states() -> None:
    area, walls, passes = _two_rooms()
    source = End(Vec(75, 300), True)
    hole = [(Vec(3000, 300), Vec(3100, 300))]
    with search_memo():
        a = Router(area, source, walls=walls, passes=passes)
        b = Router(area, source, walls=walls, passes=passes, holes=hole)
        c = Router(area, source, walls=walls, passes=passes, holes=hole)
    assert a.dist is not b.dist and b.dist is c.dist
    assert a.grid.free is b.grid.free  # the same base grid, only the penalties differ
    assert a.grid.penalty is not b.grid.penalty
