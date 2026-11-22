"""Answers applied on top of the model: code-built panel questions (apply_auto_answers)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from floorplan_engine.validation.issues import Severity
from floorplan_engine.validation.validate import validate_project
from tests.conftest import make_plan

WALLS = [{"length": 3000}, {"length": 2500}, {"length": 3000}, {"length": 2500}]


def _socket(pid: str, group: str) -> dict[str, Any]:
    return {
        "id": pid,
        "room": "r",
        "type": "socket",
        "wall": "w1",
        "offset": 500,
        "height": 300,
        "group": group,
    }


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A room with two socket groups and a backup source: the panel asks for the reserve bus."""
    project = tmp_path / "p"
    project.mkdir()
    plan = make_plan(WALLS).model_dump(mode="json", exclude_defaults=True)
    elec = {
        "points": [_socket("s1", "QF1"), _socket("s2", "QF2")],
        "board": {"room": "r", "wall": "w1", "offset": 2000, "height": 1700},
        "cables": [
            {"id": f"c{k}", "from": "board", "to": [f"s{k}"], "group": f"QF{k}", "cable": "3x2.5"}
            for k in (1, 2)
        ],
        "panel": {"backup": "inverter"},
    }
    (project / "room.yaml").write_text(yaml.safe_dump(plan, allow_unicode=True), "utf-8")
    (project / "electrical.yaml").write_text(yaml.safe_dump(elec, allow_unicode=True), "utf-8")
    return project


def _answer(project: Path, value: Any) -> None:
    text = yaml.safe_dump({"answers": {"panel_reserve": value}})
    (project / "answers.yaml").write_text(text, "utf-8")


def test_removed_group_in_a_groups_answer_is_skipped_with_a_warning(project: Path) -> None:
    """The group was removed from the model after the answer: the build goes on without it, the
    stored answer is not rewritten."""
    assert "panel_reserve" in {q.id for q in validate_project(project).auto_questions}
    _answer(project, ["QF1", "QF22"])
    report = validate_project(project)
    assert not report.errors
    assert report.electrical is not None and report.electrical.panel.reserve == ["QF1"]
    assert report.question_states["panel_reserve"] == "answered"
    warning = next(i for i in report.warnings if i.path == "answers.panel_reserve")
    assert warning.severity is Severity.WARNING
    assert warning.message == "групп QF22 больше нет в модели — пропущены"
    stored = yaml.safe_load((project / "answers.yaml").read_text("utf-8"))
    assert stored["answers"]["panel_reserve"] == ["QF1", "QF22"]


def test_groups_answer_with_no_group_left_asks_again(project: Path) -> None:
    _answer(project, ["QF22", "QF23"])
    report = validate_project(project)
    assert not report.errors
    assert report.electrical is not None and report.electrical.panel.reserve == []
    assert report.question_states["panel_reserve"] == "open"
    assert any("QF22, QF23" in i.message for i in report.warnings)


def test_malformed_groups_answer_is_an_error(project: Path) -> None:
    _answer(project, "QF1")
    report = validate_project(project)
    error = next(i for i in report.errors if i.path == "answers.panel_reserve")
    assert "ожидается список групп из: QF1, QF2" in error.message
