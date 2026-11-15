from __future__ import annotations

from pathlib import Path

import yaml

from floorplan_engine.model.furniture import Furniture
from floorplan_engine.model.geometry import trace_contour
from floorplan_engine.model.intake import Stage
from floorplan_engine.pipeline import assess_project, furniture_of
from floorplan_engine.validation.assess import Status
from floorplan_engine.validation.furniture import INSIDE_TOLERANCE, validate_furniture
from tests.conftest import make_plan

# A room 4000 × 3000 at the origin
ROOM = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]


def _check(*items: dict[str, object]) -> list[str]:
    plan = make_plan(ROOM)
    contours = {"r": trace_contour(plan.rooms[0], plan.default_wall_thickness)}
    base: dict[str, object] = {"room": "r", "kind": "kitchen", "at": [0, 0], "size": [600, 600]}
    furniture = Furniture.model_validate({"items": [base | i for i in items]})
    return [f"{i.path}: {i.message}" for i in validate_furniture(furniture, plan, contours)]


def test_room_inside_and_ids() -> None:
    assert _check({"id": "a"}, {"id": "b", "at": [3400, 2400]}) == []
    # A little over the outline is fine
    assert _check({"id": "a", "at": [-INSIDE_TOLERANCE / 2, 0]}) == []
    (out,) = _check({"id": "a", "at": [3600, 0]})
    assert out.startswith("items[0].at:") and "выходит за пол" in out and "Комната" in out
    (room,) = _check({"id": "a", "room": "nope"})
    assert room.startswith("items[0].room:") and "«nope»" in room
    (dup,) = _check({"id": "a"}, {"id": "a"})
    assert dup.startswith("items[1].id:")


def _project(tmp_path: Path, furniture: dict[str, object] | str) -> Path:
    tmp_path.mkdir()
    plan = make_plan(ROOM).model_dump(mode="json", exclude_defaults=True)
    (tmp_path / "room.yaml").write_text(yaml.safe_dump(plan, allow_unicode=True), "utf-8")
    text = furniture if isinstance(furniture, str) else yaml.safe_dump(furniture)
    (tmp_path / "furniture.yaml").write_text(text, "utf-8")
    return tmp_path


def test_the_file_is_the_furniture_stage(tmp_path: Path) -> None:
    item = {"id": "k", "room": "r", "kind": "kitchen", "at": [0, 0], "size": [600, 2000]}
    good = assess_project(_project(tmp_path / "a", {"items": [item]}))
    status = good.status(Stage.FURNITURE)
    assert status is not None and status.status is Status.READY
    found = furniture_of(good)
    assert found is not None and found.items[0].id == "k"
    bad = assess_project(_project(tmp_path / "b", {"items": [item | {"room": "nope"}]}))
    status = bad.status(Stage.FURNITURE)
    assert status is not None and status.status is Status.INVALID
    assert furniture_of(bad) is None and bad.plan_builds  # the plan still builds
    broken = assess_project(_project(tmp_path / "c", "items: [ {id: k"))
    assert any(i.file == "furniture.yaml" for i in broken.report.errors)
