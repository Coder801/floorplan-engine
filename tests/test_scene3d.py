"""3D-сцена проводки: трассы по высоте, стены с проёмами — из модели."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from floorplan_engine.scene3d import (
    DOOR_TOP_MM,
    FLOOR_Z_MM,
    WINDOW_HEIGHT_MM,
    WINDOW_SILL_MM,
    build_scene,
)
from floorplan_engine.validate import validate_plan
from floorplan_engine.wiring import box_wiring
from tests.conftest import make_plan
from tests.test_wiring import DOOR, RECT, _elec

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
            assert sum(abs(a[i] - b[i]) > 0.5 for i in range(3)) == 1  # участок по одной оси
        assert pts[0][2] == pytest.approx(2700 - r.rise_start_mm)
        assert pts[-1][2] == pytest.approx(2700 - r.rise_end_mm)
        assert max(p[2] for p in pts) == pytest.approx(2700)  # по потолку
    s1 = next(r for r in wiring.runs if r.target == "s1")
    assert scene["wires"][s1.id]["pts"][-1][2] == pytest.approx(300)  # розетка на 300


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
    scene, _ = _scene()
    spans = sorted({tuple(w["z"]) for w in scene["walls"]})
    top = WINDOW_SILL_MM + WINDOW_HEIGHT_MM
    assert spans == sorted({(0.0, 2700), (DOOR_TOP_MM, 2700), (0.0, WINDOW_SILL_MM), (top, 2700)})
    assert scene["assumed"] == {"ceiling": True, "openings": ["o1", "o2"]}
    assert all(len(w["normals"]) == 1 for w in scene["walls"])  # одна комната — без общих стен


def test_shared_partition_is_one_piece_with_both_normals() -> None:
    from floorplan_engine.schema import Plan

    def room(rid: str, x: float) -> dict[str, Any]:
        walls = [{"id": f"w{k + 1}", "length": n} for k, n in enumerate((3000, 4000, 3000, 4000))]
        return {"id": rid, "name": rid, "origin": [x, 0], "walls": walls}

    plan = Plan.model_validate(
        {
            "name": "т",
            "default_wall_thickness": 100,
            "source": "text",
            "rooms": [room("a", 0), room("b", 4100)],
        }
    )
    _, contours = validate_plan(plan)
    from floorplan_engine.draw_plan import room_geometries
    from floorplan_engine.scene3d import _walls

    walls = _walls(room_geometries(plan, contours), 2700)
    shared = [w for w in walls if len(w["normals"]) == 2]
    assert len(shared) == 1
    assert sorted(shared[0]["normals"]) == [[-1.0, 0.0], [1.0, 0.0]]
