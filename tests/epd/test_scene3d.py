"""3D wiring scene: routes by height, walls with openings, from the model."""

from __future__ import annotations

import itertools
from typing import Any

import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union

from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.epd.scene3d import FLOOR_Z_MM, build_scene
from floorplan_engine.model.geometry import DOOR_TOP_MM, WINDOW_SILL_MM
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan
from tests.electrical.test_wiring import DOOR, RECT, _elec

WINDOW = {"wall": "w3", "type": "window", "offset": 1000, "width": 1200}


def _scene(cables: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any], Any]:
    plan = make_plan(RECT, [DOOR, WINDOW])
    _, contours = validate_plan(plan)
    elec = _elec(cables)
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    return build_scene(plan, contours, elec, wiring), wiring


def test_wires_are_orthogonal_and_end_at_point_heights() -> None:
    scene, wiring = _scene()
    assert set(scene["wires"]) == {r.id for r in wiring.runs}
    for r in wiring.runs:
        pts = scene["wires"][r.id]["pts"]
        for a, b in itertools.pairwise(pts):
            assert sum(abs(a[i] - b[i]) > 0.5 for i in range(3)) == 1  # a piece along one axis
        assert pts[0][2] == pytest.approx(2700 - r.rise_start_mm)
        assert pts[-1][2] == pytest.approx(2700 - r.rise_end_mm)
        assert max(p[2] for p in pts) == pytest.approx(2700)  # on the ceiling
    s1 = next(r for r in wiring.runs if r.target == "s1")
    assert scene["wires"][s1.id]["pts"][-1][2] == pytest.approx(300)  # socket at 300
    # A line's room is the target's room: the viewer filters 3D by it
    point_rooms = {pid: p["room"] for pid, p in scene["points"].items()}
    box_rooms = {bid: b["room"] for bid, b in scene["boxes"].items()}
    for r in wiring.runs:
        assert scene["wires"][r.id]["room"] == {**point_rooms, **box_rooms}[r.target]


def test_floor_route_runs_in_screed() -> None:
    scene, wiring = _scene(
        [
            {
                "id": "c1",
                "from": "board",
                "to": ["s2"],
                "group": "QF3",
                "cable": "3x2.5",
                "route": "floor",
            }
        ]
    )
    r = next(r for r in wiring.runs if r.target == "s2")
    pts = scene["wires"][r.id]["pts"]
    assert scene["wires"][r.id]["route"] == "floor"
    assert min(p[2] for p in pts) == pytest.approx(FLOOR_Z_MM)


def test_walls_have_lintel_and_sill_and_assumptions() -> None:
    """A lintel above a door; a window without a height has only a sill: the window goes up to
    the ceiling.
    """
    scene, _ = _scene()
    spans = sorted({tuple(w["z"]) for w in scene["walls"]})
    assert spans == sorted({(0.0, 2700), (DOOR_TOP_MM, 2700), (0.0, WINDOW_SILL_MM)})
    assert scene["assumed"] == {"ceiling": True, "openings": ["o1", "o2"]}
    assert all(len(w["normals"]) == 1 for w in scene["walls"])  # one room: no shared walls


def test_window_with_given_height_keeps_lintel() -> None:
    """A window height from room.yaml is used as is: there is wall above the window; it is not an
    assumption.
    """
    window = {**WINDOW, "sill": 700, "height": 1300}
    plan = make_plan(RECT, [DOOR, window])
    _, contours = validate_plan(plan)
    elec = _elec(None)
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    scene = build_scene(plan, contours, elec, wiring)
    spans = {tuple(w["z"]) for w in scene["walls"]}
    assert {(0.0, 700), (2000.0, 2700)} <= spans
    assert scene["assumed"]["openings"] == ["o1"]  # door only


def _two_rooms(openings_a: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Walls of two 4000×3000 rooms side by side; the shared partition is a.w3 and b.w1."""
    from floorplan_engine.epd.scene3d import _walls
    from floorplan_engine.model.geometry import room_geometries
    from floorplan_engine.model.schema import Plan

    def room(rid: str, x: float) -> dict[str, Any]:
        walls = [{"id": f"w{k + 1}", "length": n} for k, n in enumerate((3000, 4000, 3000, 4000))]
        return {"id": rid, "name": rid, "origin": [x, 0], "walls": walls}

    plan = Plan.model_validate(
        {
            "name": "т",
            "default_wall_thickness": 100,
            "source": "text",
            "rooms": [{**room("a", 0), "openings": openings_a or []}, room("b", 4100)],
        }
    )
    _, contours = validate_plan(plan)
    return _walls(room_geometries(plan, contours), 2700)


def test_shared_partition_is_one_piece_with_both_normals() -> None:
    walls = _two_rooms()
    shared = [w for w in walls if len(w["normals"]) == 2]
    assert len(shared) == 1
    assert sorted(shared[0]["normals"]) == [[-1.0, 0.0], [1.0, 0.0]]


def test_all_pieces_of_a_shared_wall_share_normals() -> None:
    """A window in a partition described in only one room: the sill and lintel lie in the opening
    band, which the neighbour's body does not overlap, but it is the same wall, and the viewer cut
    must lower it entirely instead of leaving the sill at full height."""
    window = {
        "id": "o1",
        "wall": "w3",
        "type": "window",
        "offset": 1000,
        "width": 1200,
        "sill": 700,
        "height": 1300,
    }
    walls = _two_rooms([window])
    pieces = [w for w in walls if w["key"] in ("wall:a.w3", "wall:b.w1")]
    assert sorted(tuple(w["z"]) for w in pieces) == [(0.0, 700.0), (0.0, 2700), (2000.0, 2700)]
    assert all(sorted(w["normals"]) == [[-1.0, 0.0], [1.0, 0.0]] for w in pieces)
    others = [w for w in walls if w["key"] not in ("wall:a.w3", "wall:b.w1")]
    assert all(len(w["normals"]) == 1 for w in others)


def test_outer_wall_keeps_corner_at_partition() -> None:
    """The corner where a partition meets an exterior wall belongs to the exterior wall: in a cut
    view
    the partition is a low rim and the perimeter has no notch. The partition is only between the
    rooms (y 0…3000); the bottom exterior wall is solid from corner to corner."""
    walls = _two_rooms()
    partition = [w for w in walls if len(w["normals"]) == 2]
    ys = [y for w in partition for ring in w["polys"] for x, y in ring[0]]
    assert min(ys) == pytest.approx(0) and max(ys) == pytest.approx(3000)
    bottom = unary_union(
        [Polygon(ring[0]) for w in walls if w["key"].endswith(".w4") for ring in w["polys"]]
    )
    assert bottom.geom_type == "Polygon"  # no gap above the joint x 4000…4100
    assert bottom.bounds == pytest.approx((0, -100, 8100, 0))  # flat corners at w1 and b.w3


def test_corner_does_not_give_wall_a_foreign_normal() -> None:
    """A short wall (a 200 mm step) overlaps its neighbour by a corner square, a noticeable share of
    its area, but that is a joint, not a shared wall: a foreign (perpendicular) normal would make
    the cut hide the neighbouring wall when it is the far one."""
    from floorplan_engine.epd.scene3d import _walls
    from floorplan_engine.model.geometry import room_geometries

    jog = [
        {"length": 3000},
        {"length": 2000},
        {"length": 200, "turn": 270},
        {"length": 2000},
        {"length": 2800},
        {"length": 4000},
    ]
    plan = make_plan(jog)
    _, contours = validate_plan(plan)
    walls = _walls(room_geometries(plan, contours), 2700)
    assert all(len(w["normals"]) == 1 for w in walls)
