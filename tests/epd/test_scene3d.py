"""3D-сцена проводки: трассы по высоте, стены с проёмами — из модели."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

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
            assert sum(abs(a[i] - b[i]) > 0.5 for i in range(3)) == 1  # участок по одной оси
        assert pts[0][2] == pytest.approx(2700 - r.rise_start_mm)
        assert pts[-1][2] == pytest.approx(2700 - r.rise_end_mm)
        assert max(p[2] for p in pts) == pytest.approx(2700)  # по потолку
    s1 = next(r for r in wiring.runs if r.target == "s1")
    assert scene["wires"][s1.id]["pts"][-1][2] == pytest.approx(300)  # розетка на 300
    # Помещение линии — помещение цели: по нему фильтр 3D в просмотре
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
    """Над дверью — перемычка, у окна без высоты — только подоконник: окно до потолка."""
    scene, _ = _scene()
    spans = sorted({tuple(w["z"]) for w in scene["walls"]})
    assert spans == sorted({(0.0, 2700), (DOOR_TOP_MM, 2700), (0.0, WINDOW_SILL_MM)})
    assert scene["assumed"] == {"ceiling": True, "openings": ["o1", "o2"]}
    assert all(len(w["normals"]) == 1 for w in scene["walls"])  # одна комната — без общих стен


def test_window_with_given_height_keeps_lintel() -> None:
    """Высота окна из room.yaml берётся как есть: над окном — стена; допущением оно не числится."""
    window = {**WINDOW, "sill": 700, "height": 1300}
    plan = make_plan(RECT, [DOOR, window])
    _, contours = validate_plan(plan)
    elec = _elec(None)
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    scene = build_scene(plan, contours, elec, wiring)
    spans = {tuple(w["z"]) for w in scene["walls"]}
    assert {(0.0, 700), (2000.0, 2700)} <= spans
    assert scene["assumed"]["openings"] == ["o1"]  # только дверь


def test_shared_partition_is_one_piece_with_both_normals() -> None:
    from floorplan_engine.model.schema import Plan

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
    from floorplan_engine.epd.scene3d import _walls
    from floorplan_engine.model.geometry import room_geometries

    walls = _walls(room_geometries(plan, contours), 2700)
    shared = [w for w in walls if len(w["normals"]) == 2]
    assert len(shared) == 1
    assert sorted(shared[0]["normals"]) == [[-1.0, 0.0], [1.0, 0.0]]


def test_corner_does_not_give_wall_a_foreign_normal() -> None:
    """Короткая стена (уступ 200 мм) перекрывается с соседней угловым квадратом — заметная
    доля её площади, но это стык, а не общая стена: чужая (перпендикулярная) нормаль
    заставила бы «срез» прятать соседнюю стену, когда та дальняя."""
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
