"""Pipeline writes from the viewer: an answer goes through the same check as a build."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from floorplan_engine.model.intake import AnswerNote
from floorplan_engine.pipeline import assess_project, build_project, save_answer
from floorplan_engine.validation.issues import QuestionState
from tests.electrical.test_estimate import RECT
from tests.electrical.test_variants import _project

NOTE = AnswerNote(at="2026-11-04T10:00:00+00:00", by="Иван")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    folder = _project(tmp_path)
    length = RECT[0]["length"]
    intake = {
        "questions": [
            {
                "id": "q1",
                "stage": "plan",
                "target": "rooms.r.walls.w1.length",
                "also": ["rooms.r.walls.w3.length"],
                "text": "Высота комнаты на плане?",
                "answer": "value",
                "assumption": length,
            },
            {
                "id": "q2",
                "stage": "plan",
                "target": "rooms.r.walls.w1.length",
                "text": "Только левая стена?",
                "answer": "value",
                "assumption": length,
            },
            {
                "id": "q3",
                "stage": "plan",
                "text": "Есть ли обмер?",
                "answer": "text",
                "severity": "major",
            },
        ]
    }
    (folder / "intake.yaml").write_text(yaml.safe_dump(intake, allow_unicode=True), "utf-8")
    return folder


def _states(project: Path) -> dict[str, QuestionState]:
    return assess_project(project).report.question_states


def test_value_is_saved_and_needs_a_rebuild(project: Path) -> None:
    saved = save_answer(project, "q1", 4000, NOTE)
    assert saved.issues == [] and saved.rebuild
    assert _states(project)["q1"] == "answered"
    data = yaml.safe_load((project / "answers.yaml").read_text("utf-8"))
    assert data["answers"] == {"q1": 4000}
    assert data["log"]["q1"] == {"at": NOTE.at, "by": "Иван"}


def test_text_needs_no_rebuild_and_changes_no_digest(project: Path) -> None:
    built = build_project(project).assessment.report.answers_digest
    saved = save_answer(project, "q3", {"text": "  обмера нет "}, NOTE)
    assert saved.issues == [] and not saved.rebuild
    report = assess_project(project).report
    assert report.question_states["q3"] == "text"
    assert report.answers_digest == built
    assert not save_answer(project, "q3", None, None).rebuild  # removing it too
    assert not (project / "answers.yaml").read_text("utf-8").count("обмера")


def test_accept_and_remove_rebuild(project: Path) -> None:
    assert save_answer(project, "q1", {"accept": True}, NOTE).rebuild
    assert _states(project)["q1"] == "accepted"
    assert save_answer(project, "q1", None, None).rebuild
    assert _states(project)["q1"] == "open"


def test_answer_breaking_the_model_is_refused_and_file_kept(project: Path) -> None:
    (project / "answers.yaml").write_text("answers:\n  q3: { accept: true } # было\n", "utf-8")
    before = (project / "answers.yaml").read_text("utf-8")
    saved = save_answer(project, "q2", 9000, NOTE)  # one wall of a rectangle: the contour breaks
    assert saved.issues and not saved.rebuild
    assert (project / "answers.yaml").read_text("utf-8") == before


def test_refused_first_answer_leaves_no_file(project: Path) -> None:
    assert save_answer(project, "q2", 9000, NOTE).issues
    assert not (project / "answers.yaml").exists()


@pytest.mark.parametrize(
    ("qid", "raw", "message"),
    [
        ("nope", 1, "нет"),
        ("q1", True, "ожидается"),
        ("q1", [1], "ожидается"),
        ("q1", "много", "ожидается число"),
        ("q1", "  ", "пустой"),
        ("q3", 5, "нужен ответ"),
        ("q3", {"text": "  "}, "пустой"),
        ("q3", {"text": "т", "resolved": True}, "ожидается"),  # resolved — only the analyzer
        ("q3", {"text": "т" * 2001}, "длиннее"),
    ],
)
def test_bad_answers(project: Path, qid: str, raw: object, message: str) -> None:
    saved = save_answer(project, qid, raw, NOTE)
    assert message in saved.issues[0].message
    assert saved.issues[0].path == f"answers.{qid}"
    assert not (project / "answers.yaml").exists()


def test_resolved_answer_can_be_changed_not_removed(project: Path) -> None:
    (project / "answers.yaml").write_text(
        'answers:\n  q3: { text: "нет", resolved: true }\n', "utf-8"
    )
    assert "изменить" in save_answer(project, "q3", None, None).issues[0].message
    assert save_answer(project, "q3", {"text": "есть"}, NOTE).rebuild
    assert _states(project)["q3"] == "text"


def test_panel_question_and_answer_in_the_way(project: Path) -> None:
    assert not save_answer(project, "panel_battery", 48, NOTE).issues
    saved = save_answer(project, "panel_backup", "none", NOTE)
    assert saved.issues
    assert [q.id for q in saved.blocked_by] == ["panel_battery"]
    assert not save_answer(project, "panel_battery", None, None).issues
    assert not save_answer(project, "panel_backup", "none", NOTE).issues
