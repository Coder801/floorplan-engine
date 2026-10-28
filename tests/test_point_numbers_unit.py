"""Номера точек и таблица «Точки» (point_numbers.py)."""

from __future__ import annotations

from floorplan_engine.point_numbers import number_points, point_rows, points_table, ranges
from floorplan_engine.schema import Electrical
from floorplan_engine.validate import parse_model
from tests.conftest import make_plan


def test_ranges() -> None:
    assert ranges([3, 1, 2, 7]) == "1–3, 7"
    assert ranges([4, 5]) == "4, 5"
    assert ranges([9]) == "9"


def _elec() -> Electrical:
    elec, _ = parse_model(
        Electrical,
        {
            "points": [
                {"id": "c1", "type": "light", "room": "r", "ceiling": [500, 500]},
                {
                    "id": "s2",
                    "type": "socket",
                    "room": "r",
                    "wall": "w3",
                    "offset": 100,
                    "height": 300,
                },
                {
                    "id": "s1",
                    "type": "socket",
                    "room": "r",
                    "wall": "w1",
                    "offset": 900,
                    "height": 300,
                },
                {
                    "id": "s0",
                    "type": "socket",
                    "room": "r",
                    "wall": "w1",
                    "offset": 100,
                    "height": 300,
                },
                {
                    "id": "k1",
                    "type": "switch",
                    "room": "r",
                    "wall": "w1",
                    "offset": 500,
                    "height": 900,
                    "note": "коридор",
                },
            ]
        },
        "e.yaml",
    )
    assert elec is not None
    return elec


def test_numbers_follow_walls_then_ceiling() -> None:
    plan = make_plan([{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}])
    n = number_points(plan, _elec())
    assert [k for k, _ in sorted(n.items(), key=lambda kv: kv[1])] == ["s0", "k1", "s1", "s2", "c1"]


def test_same_points_share_a_row() -> None:
    plan = make_plan([{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}])
    rows = point_rows(plan, _elec())
    sockets = next(r for r in rows if r.point_ids[0] == "s0")
    assert sockets.numbers == "1, 3, 4" and sockets.height == "300" and sockets.count == 3
    switch = next(r for r in rows if r.point_ids == ("k1",))
    assert switch.name.endswith(": коридор") and switch.numbers == "2"
    table = points_table(plan, _elec())
    assert table is not None and len(table.rows) == len(rows) == 3
