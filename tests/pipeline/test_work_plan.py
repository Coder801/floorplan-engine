"""The work plan draft (pipeline/work_plan.py): both estimates in one list by stage number, and the
build puts it into the .epd manifest as `work_plan`."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import yaml

from floorplan_engine.electrical.estimate import Estimate, Line
from floorplan_engine.pipeline import ARTIFACT_FILE, OUT_DIR, build_project
from floorplan_engine.pipeline.work_plan import work_plan
from tests.conftest import make_flat
from tests.electrical.test_variants import _project


def _est(*keys: str) -> Estimate:
    return Estimate(tuple(Line("rough", k, k, "м", 1.0, 10.0) for k in keys), "грн")


def test_sections_interleave_by_stage_number() -> None:
    plan = work_plan(
        _est("work.cable", "work.chase"), _est("work.water_pipe", "work.chase_pipe"), "ru"
    )
    assert plan is not None and plan["currency"] == "грн"
    assert [t["key"] for t in plan["tasks"]] == [
        "electrical.chases",
        "plumbing.chases",
        "electrical.cable",
        "plumbing.water",
    ]
    assert [t["domain"] for t in plan["tasks"]] == [
        "electrical",
        "plumbing",
        "electrical",
        "plumbing",
    ]


def test_no_lines_no_plan() -> None:
    assert work_plan(None, None, "ru") is None
    assert work_plan(Estimate((), "грн"), None, "ru") is None
    only = work_plan(None, _est("work.pressure_test"), "uk")
    assert only is not None and [t["key"] for t in only["tasks"]] == ["plumbing.pressure"]


def _manifest(project: Path) -> dict[str, object]:
    with zipfile.ZipFile(project / OUT_DIR / ARTIFACT_FILE) as zf:
        data: dict[str, object] = json.loads(zf.read("manifest.json"))
    return data


def test_build_puts_the_draft_into_the_epd(tmp_path: Path) -> None:
    project = _project(tmp_path)
    assert build_project(project).built
    draft = _manifest(project)["work_plan"]
    assert isinstance(draft, dict) and draft["tasks"]
    keys = [t["key"] for t in draft["tasks"]]
    assert "electrical.cable" in keys and all(k.startswith("electrical.") for k in keys)
    cable = next(t for t in draft["tasks"] if t["key"] == "electrical.cable")
    assert cable["photo"] == "required" and cable["result"]
    assert any(ln["key"].startswith("cable.") for ln in cable["lines"])
    assert build_project(project).built  # the same model, the same draft
    assert _manifest(project)["work_plan"] == draft


def test_plumbing_only_project_has_plumbing_tasks(tmp_path: Path) -> None:
    (tmp_path / "room.yaml").write_text(
        yaml.safe_dump(make_flat().model_dump(mode="json"), allow_unicode=True), "utf-8"
    )
    plumbing = {
        "risers": [{"id": "r1", "room": "bath", "at": [150, 150]}],
        "fixtures": [{"id": "wc", "room": "bath", "type": "wc", "wall": "w4", "offset": 600}],
    }
    (tmp_path / "plumbing.yaml").write_text(yaml.safe_dump(plumbing), "utf-8")
    assert build_project(tmp_path).built
    draft = _manifest(tmp_path)["work_plan"]
    assert isinstance(draft, dict)
    assert {t["domain"] for t in draft["tasks"]} == {"plumbing"}
