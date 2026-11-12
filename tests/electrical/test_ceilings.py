"""Ceiling views for the "Mounting" sheet (electrical/ceilings.py) on a synthetic room."""

from __future__ import annotations

import itertools

from floorplan_engine.electrical.ceilings import (
    ceiling_views,
    dimension_key,
    dimension_spots,
    view_offsets,
)
from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.model.schema import Electrical
from floorplan_engine.validation.issues import parse_model
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

WALLS = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]
DOOR = {"wall": "w1", "type": "door", "offset": 300, "width": 800}


def _elec(points: list[dict[str, object]], **extra: object) -> Electrical:
    data = {
        "points": points,
        "board": {"room": "r", "wall": "w1", "offset": 2000, "height": 1700, "name": "ЩР"},
        **extra,
    }
    elec, issues = parse_model(Electrical, data, "e.yaml")
    assert elec is not None, issues
    return elec


SOCKET = {"room": "r", "wall": "w2", "type": "socket", "group": "QF1", "height": 300}


def _points() -> list[dict[str, object]]:
    """Two sockets on w2 and a downlight on the ceiling."""
    return [
        {"id": "s1", "offset": 1000, **SOCKET},
        {"id": "s2", "offset": 2500, **SOCKET},
        {"id": "l1", "room": "r", "ceiling": [1500, 2000], "type": "downlight", "group": "QF2"},
    ]


def test_one_ceiling_view_per_room_with_its_lines_and_ends() -> None:
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(_points())
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    views = ceiling_views(plan, contours, elec, wiring)
    assert [v.key for v in views] == ["r.ceiling"]  # no floor routes, no floor view
    view = views[0]
    assert set(view.runs) == {r.id for r in wiring.runs if r.route == "ceiling"}
    assert len(view.walls) == 4 and all(w.code for w in view.walls)
    kinds = {e.kind for e in view.ends}
    assert {"drop", "light", "board"} <= kinds
    board = next(e for e in view.ends if e.kind == "board")
    assert board.groups == ("ЩР",) and board.numbers == ()
    light = next(e for e in view.ends if e.kind == "light")
    assert light.numbers and light.groups == ("QF2",)
    assert {b.id for b in view.boxes} == {b.id for b in wiring.boxes}
    assert view.left is not None and view.bottom is not None


def test_offsets_start_at_zero_end_at_the_room_and_skip_close_values() -> None:
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(_points())
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    view = ceiling_views(plan, contours, elec, wiring)[0]
    xs, ys = view_offsets(view, wiring)
    size = view.size
    assert xs[0] == 0 and xs[-1] == round(size.x)
    assert ys[0] == 0 and ys[-1] == round(size.y)
    for values in (xs, ys):
        assert values == sorted(values)
        inner = values[1:-1]  # the room size may come closer to the last value
        assert all(b - a >= 30 for a, b in itertools.pairwise(inner))


def test_floor_route_gets_its_own_floor_view() -> None:
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(_points(), route="floor")
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    planes = {v.plane for v in ceiling_views(plan, contours, elec, wiring)}
    assert "floor" in planes


def test_each_scale_value_knows_what_it_measures() -> None:
    """The ceiling light is measured on both scales; the scale ends (walls) measure nothing of
    their own; every value has its object key."""
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(_points())
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    view = ceiling_views(plan, contours, elec, wiring)[0]
    xs, ys = dimension_spots(view, wiring)
    assert list(xs) == view_offsets(view, wiring)[0] and list(ys) == view_offsets(view, wiring)[1]
    light = next(e.at for e in view.ends if e.kind == "light")
    assert any(light in spots for spots in xs.values())
    assert any(light in spots for spots in ys.values())
    assert xs[0.0] == [] and xs[max(xs)] == []
    assert dimension_key(view, "x", 1450.0) == "dim:r.ceiling.x1450"
