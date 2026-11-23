"""Tests of electrical/box_spots.py: where a box stands, moved by hand, kept off foreign lines."""

from __future__ import annotations

from typing import Any

import pytest
from shapely.geometry import LineString, Point, Polygon

from floorplan_engine.electrical import box_spots as box_spots_module
from floorplan_engine.electrical import boxes as boxes_module
from floorplan_engine.electrical.boxes import BOX_CLEARANCE, BOX_SIZE_MM, box_square
from floorplan_engine.electrical.bundles import lane_paths
from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.model.scale import sheet
from floorplan_engine.model.schema import Electrical
from tests.conftest import make_plan
from tests.electrical.conftest import (
    DOOR,
    RECT,
    base_elec,
    edited_wiring,
    wall_point,
    wiring_of,
)


def test_box_not_in_doorway() -> None:
    w = wiring_of(make_plan(RECT, [DOOR]), base_elec())
    for b in w.boxes:
        a = b.anchor
        # The box on the top wall (w2, y = 3000) stays clear of the door 1000…1900 with a margin
        if abs(a.pos.y - 3000) < 1e-6:
            assert not (1000 - BOX_CLEARANCE < a.pos.x < 1900 + BOX_CLEARANCE)


def test_ceiling_box_in_center_of_its_points() -> None:
    """A ceiling box sits at the centre of its points, not at the wall on the panel side."""
    plan = make_plan(RECT, [DOOR])
    pts = [
        wall_point("s1", "socket", "w1", 1500, 300, "QF1"),
        wall_point("s2", "socket", "w3", 1500, 300, "QF1"),
    ]
    elec = Electrical.model_validate(
        {"points": pts, "board": {"room": "r", "wall": "w4", "offset": 500, "height": 1700}}
    )
    (box,) = wiring_of(plan, elec).boxes
    assert box.on_ceiling
    assert abs(box.anchor.node.x - 2000) <= 100 and abs(box.anchor.node.y - 1500) <= 100


def test_ceiling_route_box_is_on_ceiling_away_from_walls() -> None:
    from floorplan_engine.electrical.routing import CLEARANCE

    plan = make_plan(RECT, [DOOR])
    pts = [
        wall_point("l1", "light", "w1", 1500, 2400, "QF1"),
        wall_point("s1", "socket", "w2", 2000, 300, "QF1"),
        wall_point("s2", "socket", "w3", 1500, 300, "QF1"),
    ]
    elec = Electrical.model_validate(
        {"points": pts, "board": {"room": "r", "wall": "w4", "offset": 500, "height": 1700}}
    )
    w = wiring_of(plan, elec)
    (box,) = w.boxes
    assert box.on_ceiling and box.rise_mm == 0.0
    assert not [c for c in w.chases if c.kind == "box"]
    room = Polygon([(0, 0), (0, 3000), (4000, 3000), (4000, 0)])
    p = box.anchor.node
    assert room.exterior.distance(Point(p.x, p.y)) >= CLEARANCE - 1e-6


def test_wall_box_slides_along_its_wall() -> None:
    # A wall box only for a floor route
    elec = base_elec().model_copy(update={"route": "floor"})
    auto = wiring_of(make_plan(RECT, [DOOR]), elec)
    box = next(b for b in auto.boxes if not b.on_ceiling)
    a = box.anchor
    assert a.wall_dir is not None and a.inward is not None
    # Far along the wall and away from it: the box goes to the wall end, on the wall
    far = a.pos + a.wall_dir * 100000 + a.inward * 700
    edit = {"room": box.room, "group": box.group, "at": list(far.as_tuple())}
    w = edited_wiring({"boxes": {box.id: edit}}, elec)
    moved = next(b for b in w.boxes if b.id == box.id)
    assert moved.anchor.inward == a.inward
    assert abs((moved.anchor.pos - a.pos).cross(a.wall_dir)) < 1e-6  # on the same wall
    assert moved.anchor.pos != a.pos
    # Box lines start from the new spot
    for r in w.runs:
        if r.source == box.id:
            assert r.path[0] == moved.anchor.node
        if r.target == box.id:
            assert r.path[-1] == moved.anchor.node


def test_stale_box_edit_is_ignored() -> None:
    auto = wiring_of(make_plan(RECT, [DOOR]), base_elec())
    box = auto.boxes[0]
    w = edited_wiring({"boxes": {box.id: {"room": box.room, "group": "QF99", "at": [100, 100]}}})
    assert next(b for b in w.boxes if b.id == box.id).anchor == box.anchor
    assert w.edit_notes[0][0] == f"boxes.{box.id}"


def _passing_run_elec() -> Electrical:
    """QF1 box at the centre of two lights; the QF2 line from the panel to a socket on w3 runs
    right where that box would stand."""
    return Electrical.model_validate(
        {
            "points": [
                {"id": "l1", "room": "r", "type": "downlight", "ceiling": [1000, 1500],
                 "group": "QF1"},
                {"id": "l2", "room": "r", "type": "downlight", "ceiling": [3000, 1500],
                 "group": "QF1"},
                wall_point("s1", "socket", "w3", 1550, 300, "QF2"),
            ],
            "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
        }
    )  # fmt: skip


def _touching(wiring: Wiring) -> list[str]:
    """Boxes whose square touches a line of their plane that does not go into them (a light
    chain behind the box is its own line too, as in box_spots._box_reach)."""
    paths, _ = lane_paths(wiring.runs, wiring.free)
    out = []
    for b in wiring.boxes:
        mine = {b.id}
        for r in wiring.runs:
            if r.source in mine:
                mine.add(r.target)
        lines = [
            LineString([p.as_tuple() for p in paths[k]])
            for k, r in enumerate(wiring.runs)
            if r.route == b.route and b.id != r.target and r.source not in mine
        ]
        if any(box_square(b.anchor, sheet(BOX_SIZE_MM)).intersects(ln) for ln in lines):
            out.append(b.id)
    return out


def test_box_is_moved_off_a_line_that_passes_by(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decision 2026-11-17: a box does not stand on lines that do not go into it."""
    plan = make_plan(RECT, [DOOR])
    elec = _passing_run_elec()
    monkeypatch.setattr(box_spots_module, "BOX_CLEAR_ROUNDS", 0)
    before = wiring_of(plan, elec)
    assert _touching(before) == ["box_1"]  # the spot by the old rule is on the QF2 line
    monkeypatch.undo()
    after = wiring_of(plan, elec)
    assert _touching(after) == [] and after.box_notes == ()
    assert after.boxes[0].anchor.pos != before.boxes[0].anchor.pos
    # its own lines still go into it, the passing line is as it was
    targets = {r.target: r.source for r in after.runs}
    assert {targets["l1"], targets["l2"]} - {"box_1"} in ({"l1"}, {"l2"})  # one light set
    assert targets["box_1"] == "board"
    assert after == wiring_of(plan, elec)  # deterministic


def test_box_without_a_free_spot_stays_with_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = make_plan(RECT, [DOOR])
    place = boxes_module.place_ceiling_box

    def nowhere(*args: Any, **kw: Any) -> Any:  # no spot off the passing line
        return None if len(args) > 5 and args[5] is not None else place(*args, **kw)

    monkeypatch.setattr(box_spots_module, "place_ceiling_box", nowhere)
    w = wiring_of(plan, _passing_run_elec())
    assert _touching(w) == ["box_1"]
    assert len(w.box_notes) == 1
    box, text = w.box_notes[0]
    assert box == "box_1" and "К1" in text and "нет места" in text
