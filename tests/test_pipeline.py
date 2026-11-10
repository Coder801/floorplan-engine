"""Pipeline writes from the viewer: an answer goes through the same check as a build."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from floorplan_engine.model.intake import AnswerNote
from floorplan_engine.pipeline import (
    assess_project,
    build_project,
    save_answer,
    save_answers,
    save_variant,
    save_wizard,
)
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


def test_answers_at_once_open_the_questions_they_bring(project: Path) -> None:
    assert not save_answer(project, "panel_backup", "none", NOTE).issues
    assert save_answer(project, "panel_battery", 48, NOTE).issues  # no inverter, no such question
    saved = save_answers(
        project,
        {
            "panel_backup": "inverter",
            "panel_inverter": "basic",
            "panel_battery": 24,
            "panel_pv": 2,
            "panel_npe": "no",
        },
        NOTE,
    )
    assert not saved.issues and saved.rebuild
    elec = assess_project(project).report.electrical
    assert elec is not None
    panel = elec.panel
    assert (panel.backup, panel.inverter, panel.battery_voltage) == ("inverter", "basic", 24)
    assert (panel.pv_strings, panel.npe_relay) == (2, False)


def test_answers_at_once_replace_the_ones_in_the_way(project: Path) -> None:
    assert not save_answer(project, "panel_battery", 48, NOTE).issues
    saved = save_answers(project, {"panel_backup": "none", "panel_battery": None}, NOTE)
    assert not saved.issues and saved.rebuild
    answers = yaml.safe_load((project / "answers.yaml").read_text("utf-8"))["answers"]
    assert answers == {"panel_backup": "none"}


def test_a_refused_answer_keeps_all_of_them_out(project: Path) -> None:
    saved = save_answers(project, {"panel_backup": "none", "panel_battery": 48}, NOTE)
    assert saved.issues and not saved.rebuild
    assert not (project / "answers.yaml").exists()
    saved = save_answers(project, {"panel_input": 40, "nope": 1}, NOTE)
    assert [i.path for i in saved.issues] == ["answers.nope"]
    assert not (project / "answers.yaml").exists()


def test_wizard_writes_the_variant_and_answers_or_nothing(project: Path) -> None:
    variant = {"mode": "economy", "route": "floor", "distribution": "boxes"}
    assert save_wizard(project, {"mode": "cheap"}, {}, NOTE).issues
    assert not (project / "variant.yaml").exists()

    saved = save_wizard(project, variant, {"panel_input": -1}, NOTE)
    assert saved.issues and not saved.rebuild
    assert not (project / "variant.yaml").exists()
    assert not (project / "answers.yaml").exists()

    saved = save_wizard(project, variant, {}, NOTE)
    assert not saved.issues and saved.rebuild
    text = (project / "variant.yaml").read_text("utf-8")
    saved = save_wizard(project, {**variant, "mode": "proper"}, {"panel_input": -1}, NOTE)
    assert saved.issues
    assert (project / "variant.yaml").read_text("utf-8") == text

    saved = save_wizard(project, None, {"panel_input": 40}, NOTE)
    assert not saved.issues and saved.rebuild
    assert not save_wizard(project, None, {}, NOTE).rebuild


def _reserve_block(project: Path) -> dict[str, Any]:
    with zipfile.ZipFile(project / "out" / "project.epd") as zf:
        manifest = json.loads(zf.read("manifest.json"))
    block: dict[str, Any] = manifest["overview"]["panel"]["reserve"]
    return block


def test_backup_bus_is_answered_by_model_groups(project: Path) -> None:
    (project / "intake.yaml").unlink()
    build_project(project)
    block = _reserve_block(project)
    names = [g["id"] for g in block["items"]]
    assert len(names) >= 2 and block["limit_kw"] > 0 and block["limit_assumed"] is True
    assert {g["kind"] for g in block["items"]} <= {"light", "sockets", "heavy"}
    assert any(g["kind"] == "light" for g in block["items"])  # the "lighting only" quick pick
    keep = [names[-1]]

    assert (
        "ожидается список групп"
        in save_answer(project, "panel_reserve", ["QF99"], NOTE).issues[0].message
    )
    assert "ожидается" in save_answer(project, "panel_reserve", [], NOTE).issues[0].message
    assert save_answer(project, "panel_reserve", keep, NOTE).rebuild
    assert _states(project)["panel_reserve"] == "answered"
    build_project(project)
    assert [g["id"] for g in _reserve_block(project)["items"] if g["on"]] == keep
    assert yaml.safe_load((project / "answers.yaml").read_text("utf-8"))["answers"] == {
        "panel_reserve": keep
    }

    # Lines of a premium layout have other names: the answer holds the group, not its lines
    assert not save_variant(project, {"mode": "proper", "route": "ceiling"})
    build_project(project)
    block = _reserve_block(project)
    assert [g["id"] for g in block["items"]] == names
    assert [g["id"] for g in block["items"] if g["on"]] == keep

    # No backup: the bus and its answer go together, as in the wizard
    assert save_answer(project, "panel_backup", "none", NOTE).issues
    saved = save_answers(project, {"panel_backup": "none", "panel_reserve": None}, NOTE)
    assert not saved.issues
    build_project(project)
    assert (
        "reserve"
        not in json.loads(zipfile.ZipFile(project / "out" / "project.epd").read("manifest.json"))[
            "overview"
        ]["panel"]
    )


def test_dont_know_closes_panel_questions_with_the_assumption(project: Path) -> None:
    ids = ("panel_input", "panel_backup", "panel_inverter", "panel_battery", "panel_reserve")
    saved = save_answers(project, {qid: {"accept": True} for qid in ids}, NOTE)
    assert not saved.issues
    states = _states(project)
    assert all(states[qid] == "accepted" for qid in ids)
    elec = assess_project(project).report.electrical
    assert elec is not None and elec.panel.battery_voltage is None  # the model keeps its default
