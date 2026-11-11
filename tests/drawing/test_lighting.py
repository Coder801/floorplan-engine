"""Lighting plan (lighting.py): the "Switches" table, controls checks, links drawn at right
angles. What turns on what is tests/electrical/test_switch_links.py."""

from __future__ import annotations

import pytest

from floorplan_engine.drawing.lighting import chain, switch_rows
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.schema import Electrical
from floorplan_engine.validation.electrical import validate_electrical
from floorplan_engine.validation.issues import parse_model
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

WALLS = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]
SW = {"room": "r", "wall": "w1", "height": 900, "group": "QF1"}
CEIL = {"room": "r", "type": "downlight", "group": "QF1"}


def _elec(points: list[dict[str, object]]) -> Electrical:
    elec, issues = parse_model(Electrical, {"points": points}, "e.yaml")
    assert elec is not None, issues
    return elec


def test_switch_rows_mark_assumed() -> None:
    plan = make_plan(WALLS)
    elec = _elec(
        [
            {"id": "s1", "type": "switch", "offset": 500, **SW},
            {"id": "l1", "ceiling": [1000, 1000], **CEIL},
            {"id": "l2", "ceiling": [2000, 1000], **CEIL},
        ]
    )
    (row,) = switch_rows(plan, elec)
    assert row.controls.endswith("*") and row.group == "QF1"
    assert row.point_ids == ("s1", "l1", "l2")


def test_controls_validation() -> None:
    with pytest.raises(AssertionError):  # controls only on a switch
        _elec([{"id": "x", "type": "socket", "offset": 1, "controls": ["l1"], **SW}])
    plan = make_plan(WALLS)
    _, contours = validate_plan(plan)
    elec = _elec(
        [
            {"id": "s1", "type": "switch", "offset": 500, "controls": ["nope"], **SW},
            {"id": "l1", "ceiling": [1000, 1000], **CEIL},
        ]
    )
    issues = validate_electrical(elec, plan, contours)
    assert [i.path for i in issues] == ["points[0].controls[0]"]


def test_chain_goes_to_nearest() -> None:
    order = chain(Vec(0, 0), [("far", Vec(10, 0)), ("near", Vec(1, 0)), ("mid", Vec(5, 0))])
    assert [k for k, _ in order] == ["near", "mid", "far"]


def test_line_link_draws_straight_segments() -> None:
    """The link is straight segments between neighbouring points as one polyline, no arcs
    (2026-11-03).
    """
    from ezdxf.entities.lwpolyline import LWPolyline
    from ezdxf.filemanagement import new

    from floorplan_engine.drawing.lighting import line_link
    from floorplan_engine.model.geometry import Vec

    msp = new().modelspace()
    line_link(msp, [Vec(0, 0), Vec(1000, 0), Vec(1000, 1000)], {"layer": "E-LINK"})
    (pl,) = msp.query("LWPOLYLINE")
    assert isinstance(pl, LWPolyline)
    assert [(x, y) for x, y, *_ in pl.get_points("xy")] == [(0, 0), (1000, 0), (1000, 1000)]
    assert all(b == 0.0 for *_, b in pl.get_points("xyb"))


def test_right_angle_path_adds_elbows() -> None:
    """Links run at right angles (2026-11-11): an elbow between points not on one axis,
    horizontal first by default; points on one axis stay one leg."""
    from floorplan_engine.drawing.lighting import right_angle_path

    path = right_angle_path([Vec(0, 0), Vec(1000, 500), Vec(1000, 1500)])
    assert [v.as_tuple() for v in path] == [(0, 0), (1000, 0), (1000, 500), (1000, 1500)]
    assert right_angle_path([]) == []


def test_right_angle_path_first_leg_leaves_the_wall() -> None:
    from floorplan_engine.drawing.lighting import right_angle_path

    path = right_angle_path([Vec(0, 0), Vec(1000, 500)], first=Vec(0, 1))
    assert [v.as_tuple() for v in path] == [(0, 0), (0, 500), (1000, 500)]


def test_right_angle_path_keeps_elbow_inside() -> None:
    """An L-shaped room: the elbow that would leave the room loses."""
    from shapely.geometry import Polygon

    from floorplan_engine.drawing.lighting import right_angle_path

    room = Polygon([(0, 0), (2000, 0), (2000, 1000), (1000, 1000), (1000, 2000), (0, 2000)])
    path = right_angle_path([Vec(1500, 500), Vec(500, 1500)], room)
    assert [v.as_tuple() for v in path] == [(1500, 500), (500, 500), (500, 1500)]
