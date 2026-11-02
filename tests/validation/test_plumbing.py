from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from floorplan_engine.model.plumbing import Plumbing
from floorplan_engine.validation.assess import Status, assess
from floorplan_engine.validation.issues import Severity
from floorplan_engine.validation.plan import validate_plan
from floorplan_engine.validation.plumbing import validate_plumbing
from floorplan_engine.validation.validate import validate_project
from tests.conftest import make_flat


def check(**data: Any) -> list[str]:
    plan = make_flat()
    _, contours = validate_plan(plan)
    issues = validate_plumbing(Plumbing.model_validate(data), plan, contours)
    return [f"{i.severity.value}|{i.path}|{i.message}" for i in issues]


def test_ok() -> None:
    assert (
        check(
            risers=[{"id": "r1", "room": "bath", "at": [150, 150]}],
            fixtures=[{"id": "wc", "room": "bath", "type": "wc", "wall": "w4", "offset": 600}],
        )
        == []
    )


def test_bad_wall_and_offset() -> None:
    out = check(
        risers=[{"id": "r1", "room": "bath", "at": [150, 150]}],
        fixtures=[
            {"id": "a", "room": "bath", "type": "wc", "wall": "w9", "offset": 600},
            {"id": "b", "room": "bath", "type": "wc", "wall": "w4", "offset": 5000},
        ],
    )
    assert any("fixtures[0].wall" in m and "стены «w9» нет" in m for m in out)
    assert any("fixtures[1].offset" in m for m in out)


def test_drain_without_sewer_riser_is_error() -> None:
    out = check(fixtures=[{"id": "s", "room": "bath", "type": "sink", "wall": "w1", "offset": 900}])
    assert any(m.startswith(Severity.ERROR.value) and "|risers|" in m for m in out)


def test_wet_fixture_in_dry_room_warns_kitchen_sink_does_not() -> None:
    out = check(
        risers=[{"id": "r1", "room": "bath", "at": [150, 150]}],
        fixtures=[
            {"id": "sh", "room": "kitchen", "type": "shower", "wall": "w2", "offset": 900},
            {"id": "k", "room": "kitchen", "type": "kitchen_sink", "wall": "w2", "offset": 2000},
        ],
    )
    assert [m for m in out if "wet: true" in m] == [m for m in out if "fixtures[0].room" in m]
    assert len([m for m in out if "wet: true" in m]) == 1


def test_riser_far_outside_room() -> None:
    out = check(risers=[{"id": "r1", "room": "bath", "at": [9000, 9000]}])
    assert any("risers[0].at" in m for m in out)


def test_duplicate_id_with_plan_opening() -> None:
    out = check(
        risers=[{"id": "bath_door", "room": "bath", "at": [150, 150]}],
    )
    assert any("уже есть" in m for m in out)


def test_project_stage_builds(tmp_path: Path) -> None:
    plan = make_flat()
    (tmp_path / "room.yaml").write_text(
        yaml.safe_dump(plan.model_dump(mode="json"), allow_unicode=True), encoding="utf-8"
    )
    (tmp_path / "plumbing.yaml").write_text(
        yaml.safe_dump(
            {
                "risers": [{"id": "r1", "room": "bath", "at": [150, 150]}],
                "fixtures": [
                    {"id": "wc", "room": "bath", "type": "wc", "wall": "w4", "offset": 600}
                ],
            }
        ),
        encoding="utf-8",
    )
    report = validate_project(tmp_path)
    assert report.ok and report.plumbing is not None
    stage = next(r for r in assess(report) if r.stage.value == "plumbing")
    assert stage.status is Status.READY
