from __future__ import annotations

import math

import pytest
import shapely

from floorplan_engine.drawing.callouts import (
    Board,
    Candidate,
    Kind,
    Label,
    Obstacle,
    readable_angle,
    reading,
)
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.scale import drawing_scale, sheet

ALONG_X = Vec(1.0, 0.0)
ORIGIN = Vec(0.0, 0.0)


def _label(anchor: Vec = ORIGIN, owner: str = "dimension:r.w1") -> Label:
    d, up = reading(ALONG_X)
    return Label(sheet(6.0), sheet(2.5), d, up, anchor, owner)


def _line(a: tuple[float, float], b: tuple[float, float], owner: str = "") -> Obstacle:
    return Obstacle(shapely.LineString([a, b]), Kind.LINE, owner, owner)


@pytest.mark.parametrize(("angle", "expected"), [(0, 0), (180, 0), (-90, 90), (270, 90)])
def test_readable_angle(angle: float, expected: float) -> None:
    assert readable_angle(angle) == pytest.approx(expected)


def test_reading_never_upside_down() -> None:
    d, up = reading(Vec(-1.0, 0.0))
    assert (d, up) == (Vec(1.0, -0.0), Vec(0.0, 1.0))


def test_free_own_spot_has_no_leader() -> None:
    with drawing_scale(50):
        board = Board([])
        label = _label()
        spot = board.place(label, [Candidate(Vec(0.0, 100.0))])
        assert spot.centre == Vec(0.0, 100.0) and spot.leader == ()
        # The placed text is now an obstacle for the next label on the same spot
        again = board.place(_label(owner="dimension:r.w2"), [Candidate(Vec(0.0, 100.0))])
        assert again.leader and not again.box.intersects(spot.box)


def test_taken_spot_goes_on_a_45_degree_leader_off_everything() -> None:
    """Lines all round the anchor at 1 sheet mm: the label goes out on a leader whose first
    segment is at 45°, its text off every line and the leader crossing none of them."""
    with drawing_scale(50):
        r = sheet(4.0)
        lines = [_line((-r, y), (r, y)) for y in (-50.0, 50.0)]
        lines += [_line((x, -r), (x, r)) for x in (-50.0, 50.0)]
        # The anchor's own line: the leader may start on it
        lines.append(_line((-r, 0.0), (r, 0.0), "dimension:r.w1"))
        board = Board(lines)
        spot = board.place(_label(), [Candidate(Vec(0.0, 100.0))])
        anchor, elbow, end = spot.leader
        first = elbow - anchor
        assert abs(abs(first.x) - abs(first.y)) < 1e-6  # 45°
        assert abs(end.y - elbow.y) < 1e-6  # the shelf runs along the text
        assert not any(spot.box.intersects(o.geom) for o in lines)
        tail = shapely.LineString([elbow.as_tuple(), end.as_tuple()])
        assert not any(tail.intersects(o.geom) for o in lines)


def test_inside_area_is_kept_for_own_spots() -> None:
    with drawing_scale(50):
        room = shapely.box(0.0, 0.0, 1000.0, 1000.0)
        board = Board([])
        outside, inside = Vec(-500.0, 500.0), Vec(500.0, 500.0)
        spot = board.place(_label(), [Candidate(outside), Candidate(inside)], within=room)
        assert spot.centre == inside


def test_zones_only_for_labels_that_ask() -> None:
    with drawing_scale(50):
        swing = Obstacle(shapely.box(-500.0, -500.0, 500.0, 500.0), Kind.ZONE, "opening:d")
        dim = Board([swing]).place(_label(), [Candidate(Vec(0.0, 0.0))])
        assert dim.leader == ()
        code = Board([swing]).place(_label(), [Candidate(Vec(0.0, 0.0))], zones=True)
        assert code.leader != ()


def test_no_free_spot_takes_the_least_bad_one() -> None:
    """Everything is covered by a label: the label stays where it touches the fewest."""
    with drawing_scale(50):
        cover = Obstacle(shapely.box(-1e5, -1e5, 1e5, 1e5), Kind.LINE)
        board = Board([cover])
        spot = board.place(_label(), [Candidate(Vec(0.0, 100.0))])
        assert spot.centre == Vec(0.0, 100.0) and spot.leader == ()


def test_leader_may_start_across_a_label_over_its_anchor() -> None:
    """A room name wider than its room lies over the anchor: the leader crosses it to get out."""
    with drawing_scale(50):
        board = Board([_line((-1e4, 0.0), (1e4, 0.0), "dimension:r.w1")])
        board.add(Obstacle(shapely.box(-400.0, -300.0, 400.0, 300.0), Kind.LABEL))
        spot = board.place(_label(), [Candidate(Vec(0.0, 100.0))])
        assert spot.leader
        assert not spot.box.intersects(shapely.box(-400.0, -300.0, 400.0, 300.0))
        assert math.isclose(abs((spot.leader[1] - spot.leader[0]).x), abs(spot.leader[1].y))


def _blocked_own_spot(board: Board, anchor: Vec) -> Candidate:
    """An own spot (well below the anchor) covered by a label, so the label has to go on a
    leader."""
    c = anchor + Vec(0.0, -600.0)
    board.add(Obstacle(shapely.box(c.x - 50, c.y - 50, c.x + 50, c.y + 50), Kind.LABEL))
    return Candidate(c)


def test_shortest_leader_wins_then_the_one_crossing_fewer_lines() -> None:
    """Below the anchor is taken; above, a short line crosses the up-right diagonal: the
    leader is still the shortest, but up-left, where it crosses nothing."""
    with drawing_scale(50):
        line = _line((0.0, 60.0), (100.0, 60.0))
        board = Board([line])
        board.add(Obstacle(shapely.box(-1e4, -1e4, 1e4, -20.0), Kind.LABEL))
        spot = board.place(_label(), [Candidate(Vec(0.0, -600.0))])
        anchor, elbow, _ = spot.leader
        assert (elbow - anchor).length() == pytest.approx(sheet(2.5))
        assert elbow.x < 0 < elbow.y


def test_leaders_do_not_cross_each_other() -> None:
    with drawing_scale(50):
        board = Board([])
        first = board.place(_label(), [_blocked_own_spot(board, Vec(0.0, 0.0))])
        second = board.place(
            _label(Vec(150.0, 0.0), "dimension:r.w2"), [_blocked_own_spot(board, Vec(150.0, 0.0))]
        )
        a = shapely.LineString([p.as_tuple() for p in first.leader])
        b = shapely.LineString([p.as_tuple() for p in second.leader])
        assert not a.intersects(b)


def test_leader_does_not_cross_a_wall() -> None:
    """A thin wall just above the anchor: the text could sit above it, but the leader would
    cross the wall, so the label goes down."""
    with drawing_scale(50):
        wall = Obstacle(shapely.box(-1e4, 20.0, 1e4, 40.0), Kind.WALL, "wall:r.w9")
        board = Board([wall])
        spot = board.place(_label(), [_blocked_own_spot(board, Vec(0.0, 0.0))])
        assert spot.leader[1].y < 0
