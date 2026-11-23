"""Tests of electrical/wiring_routes.py: the routing order and the ready holes, box leads,
internet apart from power, manual routes."""

from __future__ import annotations

import itertools
from typing import Any

import pytest
from shapely.geometry import LineString

from floorplan_engine.electrical.routing import WALL_HOLE_SHARE
from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.electrical.wiring_routes import BOX_LEAD_MM
from floorplan_engine.model.schema import Electrical
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan
from tests.electrical.conftest import (
    DOOR,
    RECT,
    base_elec,
    crossings_of,
    edited_wiring,
    two_rooms_with_door,
    wiring_of,
)


def _box_sides(w: Wiring) -> dict[str, set[tuple[float, float]]]:
    """Sides the cables of each box with 2-3 cables take: the unit direction at the box end."""
    out: dict[str, set[tuple[float, float]]] = {}
    for b in w.boxes:
        runs = [r for r in w.runs if b.id in (r.source, r.target)]
        if not b.on_ceiling or not 2 <= len(runs) <= 3:
            continue
        sides = set()
        for r in runs:
            a, c = (r.path[0], r.path[1]) if r.source == b.id else (r.path[-1], r.path[-2])
            d = c - a
            sides.add((round(d.x / d.length(), 3), round(d.y / d.length(), 3)))
        out[b.id] = sides
    return out


def test_box_with_few_cables_takes_them_from_one_side() -> None:
    w = wiring_of(make_plan(RECT, [DOOR]), base_elec())
    sides = _box_sides(w)
    assert sides  # the QF3 box: feed and two sockets
    assert all(len(s) == 1 for s in sides.values())
    for b in w.boxes:
        for r in w.runs:
            if b.id in sides and b.id in (r.source, r.target):
                # The lead is straight out of the box, at least BOX_LEAD_MM long in all
                end = r.path[1] if r.source == b.id else r.path[-2]
                assert (end - b.anchor.node).length() >= BOX_LEAD_MM - 50  # grid snap


def test_internet_runs_apart_from_power() -> None:
    """Decision 2026-11-13: the internet line leaves the panel with the power lines, then goes
    beside them no closer than 150 mm and comes close again only at its own end."""
    from floorplan_engine.electrical.routing import APART, beside_mm, is_ortho, length

    w = wiring_of(make_plan(RECT, [DOOR]), base_elec())
    power = [r.path for r in w.runs if r.circuit == "power"]
    lan = next(r for r in w.runs if r.target == "d1")
    assert is_ortho(lan.path) and lan.plan_mm == pytest.approx(length(lan.path))
    assert beside_mm(lan.path, power) <= 2 * APART  # the first step from the panel and the last
    assert lan.id == "wire_9" and [r.id for r in w.runs] == [f"wire_{k}" for k in range(1, 10)]


def _two_lines_into_room_b(route: str | None = None) -> Any:
    """Panel in a at y 300 (facing the wall, the door at y 1200…2000 is a detour); s1 on the top
    wall of b far to the right, s2 on the right wall of b at y 1500, facing the door; each a
    direct line of its own group."""
    pts = [
        {"id": "s1", "room": "b", "type": "socket", "wall": "w2", "offset": 2700, "height": 300,
         "group": "QF1"},
        {"id": "s2", "room": "b", "type": "socket", "wall": "w3", "offset": 1500, "height": 300,
         "group": "QF2"},
    ]  # fmt: skip
    data: dict[str, Any] = {
        "points": pts,
        "board": {"room": "a", "wall": "w1", "offset": 300, "height": 1700},
    }
    if route is not None:
        data["cables"] = [
            {"id": f"c{k}", "from": "board", "to": [p["id"]], "group": p["group"],
             "cable": "3x2.5", "route": route}
            for k, p in enumerate(pts)
        ]  # fmt: skip
    return wiring_of(two_rooms_with_door(), Electrical.model_validate(data))


def test_lines_of_one_source_follow_into_one_hole() -> None:
    """Decision 2026-11-23: the far line (s1) pays a hole through the wall at the panel's height;
    the nearer s2, whose own way lay above the door (an opening lower than the ceiling costs the
    pass too), is as short through that ready hole and takes it: one hole in the estimate, none
    above the door."""
    w = _two_lines_into_room_b()
    by_target = {r.target: r for r in w.runs}
    at = {t: crossings_of(r) for t, r in by_target.items()}
    assert len(at["s1"]) == 1 and len(at["s2"]) == 1
    assert abs(at["s1"][0] - at["s2"][0]) < WALL_HOLE_SHARE
    assert not any(1200 <= y <= 2000 for ys in at.values() for y in ys)
    (hole,) = w.holes
    assert hole.passage.startswith("wall:0:ceiling:") and set(hole.runs) == set(by_target_ids(w))
    # Routed again, the same: the order within the panel is fixed, not by hash or dict order
    assert [r.path for r in _two_lines_into_room_b().runs] == [r.path for r in w.runs]
    assert [r.id for r in w.runs] == ["wire_1", "wire_2"]  # ids by link, whatever the order


def by_target_ids(w: Wiring) -> list[str]:
    return [r.id for r in w.runs]


def test_on_the_floor_the_opening_is_free() -> None:
    """The same two lines on the floor: under the door there is no wall, so the opening costs
    nothing and both lines go through it (the way round through the wall would pay a hole); no
    hole in the estimate."""
    w = _two_lines_into_room_b("floor")
    at = {r.target: crossings_of(r) for r in w.runs}
    assert all(1200 <= y <= 2000 for ys in at.values() for y in ys) and all(at.values())
    assert w.holes == ()


def test_manual_wire_path_replaces_route() -> None:
    auto = wiring_of(make_plan(RECT, [DOOR]), base_elec())
    run = next(r for r in auto.runs if r.target == "s1")
    a, b = run.path[0], run.path[-1]
    # Detour through the room middle: right from the panel, up to 1500, to the socket
    path = [[a.x, a.y], [1500, a.y], [1500, b.y], [b.x, b.y]]
    w = edited_wiring({"wires": {run.id: {"from": "board", "to": "s1", "path": path}}})
    manual = next(r for r in w.runs if r.id == run.id)
    assert [v.as_tuple() for v in manual.path] == [tuple(p) for p in path]
    assert manual.plan_mm == pytest.approx(abs(1500 - a.x) + abs(b.y - a.y) + abs(b.x - 1500))
    assert w.edited == {f"wire:{run.id}"} and not w.edit_notes


def test_stale_wire_edit_is_ignored() -> None:
    w = edited_wiring(
        {"wires": {"wire_1": {"from": "box_9", "to": "s1", "path": [[0, 0], [0, 10]]}}}
    )
    assert not w.edited
    [(path, msg)] = w.edit_notes
    assert path == "wires.wire_1" and "не найдена" in msg


def test_diagonal_wire_edit_only_in_economy() -> None:
    """A slanted edit piece is not applied in standard (a warning) and is applied in economy
    (docs/wiring-variants.md)."""
    from floorplan_engine.model.schema import WiringEdits

    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    auto = wiring_of(plan, base_elec())
    run = next(r for r in auto.runs if r.target == "s1")
    a, b = run.path[0], run.path[-1]
    path = [[a.x, a.y], [1500, 1500], [b.x, b.y]]  # straight through the room middle
    edits = WiringEdits.model_validate(
        {"wires": {run.id: {"from": run.source, "to": "s1", "path": path}}}
    )
    standard = box_wiring(plan, contours, base_elec(), edits)
    assert standard is not None and not standard.edited
    [(where, msg)] = standard.edit_notes
    assert where == f"wires.{run.id}" and "кратчайшем пути" in msg
    economy_elec = base_elec().model_copy(update={"mode": "economy"})
    economy = box_wiring(plan, contours, economy_elec, edits)
    assert economy is not None and economy.edited == {f"wire:{run.id}"}


def test_economy_routes_shorter_at_any_angle() -> None:
    """Economy: on the ceiling along the shortest path at any angle, at least 150 mm from walls;
    standard at right angles. The economy variant uses no more cable."""

    from floorplan_engine.electrical.routing import CLEARANCE, free_area, is_ortho
    from floorplan_engine.model.geometry import room_geometries

    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    standard = wiring_of(plan, base_elec())
    economy = wiring_of(plan, base_elec().model_copy(update={"mode": "economy"}))
    assert all(is_ortho(r.path) for r in standard.runs)
    assert any(not is_ortho(r.path) for r in economy.runs)  # has slanted pieces
    assert sum(r.plan_mm for r in economy.runs) < sum(r.plan_mm for r in standard.runs)
    # Cut pieces do not enter the band by the walls (except the approach to a point right at the
    # wall)
    inner = free_area(room_geometries(plan, contours)).buffer(-CLEARANCE + 2)
    for r in economy.runs:
        for p, q in itertools.pairwise(r.path[1:-1]):
            if abs(p.x - q.x) > 1 and abs(p.y - q.y) > 1:
                assert inner.covers(LineString([p.as_tuple(), q.as_tuple()]))
