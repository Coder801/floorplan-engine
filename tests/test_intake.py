from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from floorplan_engine.assess import WEIGHT_LIMIT, Status, assess, severity
from floorplan_engine.cli import app
from floorplan_engine.intake import Intake, QSeverity, Question, Stage, index_path
from floorplan_engine.report import render_markdown, to_json
from floorplan_engine.validate import parse_model, validate_project

ROOM = {
    "name": "Тест",
    "default_wall_thickness": 120,
    "source": "text",
    "rooms": [
        {
            "id": "r",
            "name": "Комната",
            "walls": [
                {"id": "w1", "length": 3000},
                {"id": "w2", "length": 4000},
                {"id": "w3", "length": 3000},
                {"id": "w4", "length": 4000},
            ],
            "openings": [
                {"id": "win", "wall": "w3", "type": "window", "offset": 500, "width": 1200}
            ],
        }
    ],
}
ELEC = {
    "points": [
        {"id": "s1", "room": "r", "wall": "w2", "offset": 500, "type": "socket", "height": 300}
    ]
}


def _q(**fields: Any) -> dict[str, Any]:
    return {"id": "q", "stage": "plan", "text": "?", **fields}


def _project(tmp_path: Path, intake: dict[str, Any] | None = None, **files: Any) -> Path:
    data = {"room.yaml": ROOM, "electrical.yaml": ELEC, **files}
    for name, content in data.items():
        if content is not None:
            (tmp_path / name).write_text(yaml.safe_dump(content, allow_unicode=True), "utf-8")
    if intake is not None:
        (tmp_path / "intake.yaml").write_text(yaml.safe_dump(intake, allow_unicode=True), "utf-8")
    return tmp_path


def _statuses(path: Path) -> dict[Stage, Status]:
    return {r.stage: r.status for r in assess(validate_project(path))}


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"target": "rooms.r.walls.w2.length", "assumption": 4000}, QSeverity.MAJOR),
        ({"target": "rooms.r.walls.w2.length"}, QSeverity.CRITICAL),  # значения нет
        ({"target": "rooms.r.openings.win.offset"}, QSeverity.MAJOR),
        ({"target": "rooms.r.openings.win.sill"}, QSeverity.MINOR),
        ({"severity": "critical"}, QSeverity.CRITICAL),  # общий вопрос — вес от анализатора
    ],
)
def test_severity_rules(fields: dict[str, Any], expected: QSeverity) -> None:
    assert severity(Question.model_validate(_q(**fields))) is expected


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"answer": "choice", "target": "a.b"}, "options"),
        ({"target": "a.b", "severity": "minor"}, "вес считает код"),
        ({}, "нужен severity"),
        ({"answer": "value", "severity": "minor"}, "нужен target"),
    ],
)
def test_question_schema(fields: dict[str, Any], message: str) -> None:
    intake, issues = parse_model(Intake, {"questions": [_q(**fields)]}, "intake.yaml")
    assert intake is None
    assert message in " ".join(i.message for i in issues)


def test_index_path() -> None:
    assert index_path(ROOM, "rooms.r.openings.win.sill") == "rooms[0].openings[0].sill"


def test_value_answer_is_applied_without_touching_yaml(tmp_path: Path) -> None:
    q = _q(target="rooms.r.walls.w2.length", also=["rooms.r.walls.w4.length"], answer="value")
    path = _project(tmp_path, {"questions": [{**q, "assumption": 4000}]})
    (path / "answers.yaml").write_text("answers:\n  q: 4500\n", "utf-8")
    report = validate_project(path)
    assert report.ok, report.issues
    assert report.question_states == {"q": "answered"}
    assert report.plan is not None
    assert [w.length for w in report.plan.rooms[0].walls] == [3000, 4500, 3000, 4500]
    assert "4500" not in (path / "room.yaml").read_text("utf-8")


@pytest.mark.parametrize(
    ("answer", "state"), [("{ accept: true }", "accepted"), ("{ text: обмера нет }", "text")]
)
def test_accept_and_text_answers(tmp_path: Path, answer: str, state: str) -> None:
    path = _project(tmp_path, {"questions": [_q(answer="text", severity="major")]})
    (path / "answers.yaml").write_text(f"answers:\n  q: {answer}\n", "utf-8")
    report = validate_project(path)
    assert report.question_states == {"q": state}
    (plan,) = [r for r in assess(report) if r.stage is Stage.PLAN]
    # Текстовый ответ ждёт анализатора — вопрос остаётся открытым
    assert bool(plan.open_questions) is (state == "text")


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        ("q: 7", "нужен ответ { text"),
        ("nope: 1", "вопроса «nope» нет"),
    ],
)
def test_bad_answers(tmp_path: Path, answers: str, message: str) -> None:
    path = _project(tmp_path, {"questions": [_q(answer="text", severity="minor")]})
    (path / "answers.yaml").write_text(f"answers:\n  {answers}\n", "utf-8")
    errors = [i for i in validate_project(path).errors if i.file == "answers.yaml"]
    assert errors and message in errors[0].message


def test_target_must_exist(tmp_path: Path) -> None:
    path = _project(tmp_path, {"questions": [_q(target="rooms.r.walls.w9.length")]})
    (issue,) = validate_project(path).errors
    assert issue.path == "questions[0].target" and "w9" in issue.message


def test_stage_statuses(tmp_path: Path) -> None:
    intake = {
        "stages": {
            "plumbing": {"status": "absent", "note": "на листах нет сантехники"},
            "furniture": {"status": "found"},
        },
        "questions": [_q(target="rooms.r.openings.win.sill", answer="value")],
    }
    statuses = _statuses(_project(tmp_path, intake))
    assert statuses == {
        Stage.PLAN: Status.QUESTIONS,
        Stage.ELECTRICAL: Status.READY,
        Stage.FURNITURE: Status.UNSUPPORTED,
        Stage.PLUMBING: Status.ABSENT,
    }


def test_critical_question_stops_plan_and_blocks_electrical(tmp_path: Path) -> None:
    intake = {"questions": [_q(severity="critical")]}
    assert _statuses(_project(tmp_path, intake)) == {
        Stage.PLAN: Status.INSUFFICIENT,
        Stage.ELECTRICAL: Status.BLOCKED,
    }


def test_too_many_questions_is_insufficient(tmp_path: Path) -> None:
    n = WEIGHT_LIMIT // 3 + 1  # важные по 3
    questions = [{**_q(severity="major"), "id": f"q{k}"} for k in range(n)]
    assert (
        _statuses(_project(tmp_path, {"questions": questions}))[Stage.PLAN] is Status.INSUFFICIENT
    )


def test_only_intake_without_plan(tmp_path: Path) -> None:
    intake = {"questions": [_q(severity="critical", text="Нет ни одного размера")]}
    path = _project(tmp_path, intake, **{"room.yaml": None, "electrical.yaml": None})
    report = validate_project(path)
    assert report.ok  # нет room.yaml — не ошибка, если есть intake
    assert _statuses(path)[Stage.PLAN] is Status.INSUFFICIENT


def test_electrical_errors_do_not_stop_plan(tmp_path: Path) -> None:
    bad = {"points": [{**ELEC["points"][0], "wall": "w9"}]}
    path = _project(tmp_path, {"questions": []}, **{"electrical.yaml": bad})
    statuses = _statuses(path)
    assert statuses[Stage.PLAN] is Status.READY
    assert statuses[Stage.ELECTRICAL] is Status.INVALID
    result = CliRunner().invoke(app, ["build", str(path)])
    assert result.exit_code == 0, result.output
    assert (path / "out" / "project.dxf").exists()


def test_report_files(tmp_path: Path) -> None:
    intake = {
        "questions": [
            _q(target="rooms.r.walls.w2.length", assumption=4000, answer="value", unit="mm"),
            {**_q(severity="critical", text="Где щит?"), "id": "q2", "stage": "electrical"},
        ]
    }
    path = _project(tmp_path, intake)
    report = validate_project(path)
    results = assess(report)
    md = render_markdown("Тест", report, results)
    assert "## Критичные" in md and "## Важные" in md and "Где щит?" in md
    data = json.loads(to_json("Тест", report, results))
    assert {s["stage"]: s["builds"] for s in data["stages"]} == {"plan": True, "electrical": False}
    assert {q["id"]: q["severity"] for q in data["questions"]} == {"q": "major", "q2": "critical"}

    result = CliRunner().invoke(app, ["build", str(path)])
    assert result.exit_code == 0, result.output
    assert (path / "out" / "report.md").exists() and (path / "out" / "report.json").exists()


def test_build_stops_when_plan_is_insufficient(tmp_path: Path) -> None:
    path = _project(tmp_path, {"questions": [_q(severity="critical")]})
    result = CliRunner().invoke(app, ["build", str(path)])
    assert result.exit_code == 1
    assert (path / "out" / "report.md").exists()
    assert not (path / "out" / "project.dxf").exists()
