"""Where the cable goes into a frame of mechanisms (frames.py, decision 2026-11-17)."""

from __future__ import annotations

from typing import Any

from floorplan_engine.electrical.frames import POST_PITCH_MM, entries, frames, posts
from floorplan_engine.electrical.wiring_model import Run
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.schema import ElectricalPoint

X = 1000.0  # frame middle on the wall
ALONG = Vec(1.0, 0.0)  # the wall runs along x on the plan, offset grows to the right


def _point(pid: str, kind: str, count: int = 1, offset: float = X, **extra: Any) -> ElectricalPoint:
    return ElectricalPoint.model_validate(
        {
            "id": pid,
            "room": "r",
            "type": kind,
            "wall": "w1",
            "offset": offset,
            "height": 300,
            "group": "QF1",
            **({"count": count} if count > 1 else {}),
            **extra,
        }
    )


def _run(target: str, came_from: Vec, rise: float = 2400.0, drop: float | None = None) -> Run:
    """A line coming to target at plan (X, 0) from came_from along the ceiling."""
    path = (came_from, Vec(X, 0.0))
    return Run(
        "wire_1", "QF1", "3x2.5", False, "board", target, path, 0.0, 0.0, rise, 200.0, end_drop=drop
    )


def _entries(points: list[ElectricalPoint], runs: list[Run]) -> dict[str, float]:
    return entries(points, runs, {p.id: ALONG for p in points})


def test_block_of_sockets_entered_at_the_outer_edge_the_cable_comes_from() -> None:
    block = [_point("s1", "socket", count=4)]
    half = 2 * POST_PITCH_MM
    assert _entries(block, [_run("s1", Vec(0.0, 0.0))]) == {"s1": X - half}  # from the left
    assert _entries(block, [_run("s1", Vec(3000.0, 0.0))]) == {"s1": X + half}  # from the right


def test_route_square_to_the_wall_enters_at_the_wall_start_side() -> None:
    block = [_point("s1", "socket", count=2)]
    square = Run(
        "wire_1",
        "QF1",
        "3x2.5",
        False,
        "board",
        "s1",
        (Vec(2000.0, 900.0), Vec(X, 900.0), Vec(X, 0.0)),
        0.0,
        0.0,
        2400.0,
        200.0,
    )
    # The last leg is square to the wall: the leg before it says where the cable comes from
    assert _entries(block, [square]) == {"s1": X + POST_PITCH_MM}
    assert _entries(block, []) == {"s1": X - POST_PITCH_MM}  # no route: the wall start side


def test_switch_and_sockets_entered_between_them() -> None:
    frame = [_point("k1", "switch"), _point("s1", "socket", count=3)]
    out = _entries(frame, [_run("s1", Vec(3000.0, 0.0)), _run("k1", Vec(0.0, 0.0))])
    joint = X - 2 * POST_PITCH_MM + POST_PITCH_MM  # one post from the left edge
    assert out == {"k1": joint, "s1": joint}


def test_sockets_then_switch_entered_between_them() -> None:
    frame = [_point("s1", "socket", count=2), _point("k1", "switch")]
    joint = X - 1.5 * POST_PITCH_MM + 2 * POST_PITCH_MM
    assert _entries(frame, []) == {"s1": joint, "k1": joint}


def test_low_voltage_gets_its_own_entry_at_the_right_edge() -> None:
    frame = [_point("d1", "data"), _point("s1", "socket", count=2)]
    assert [p.id for p in frames(frame)[0]] == ["s1", "d1"]  # internet to the right
    out = _entries(frame, [_run("s1", Vec(3000.0, 0.0))])
    assert out == {"s1": X - 1.5 * POST_PITCH_MM, "d1": X + 1.5 * POST_PITCH_MM}


def test_points_without_a_flush_box_keep_the_drop_above_them() -> None:
    sconce = _point("b1", "sconce")
    assert _entries([sconce], [_run("b1", Vec(0.0, 0.0))]) == {}


def test_drop_beside_an_opening_does_not_choose_the_side() -> None:
    block = [_point("s1", "socket", count=2)]
    beside = _run("s1", Vec(3000.0, 0.0), drop=500.0)
    assert _entries(block, [beside]) == {"s1": X - POST_PITCH_MM}  # as with no route


def test_posts_by_type() -> None:
    assert posts(_point("s1", "socket", count=3)) == 3
    assert posts(_point("k1", "switch")) == 1
