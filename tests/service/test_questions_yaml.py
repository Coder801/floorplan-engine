"""Questions and answers as YAML text (service/db/questions_yaml.py): read into fields with the
comments next to them, written back the same byte for byte when nothing changed, and only the
changed part rewritten otherwise."""

from __future__ import annotations

import yaml

from floorplan_engine.service.db import questions_yaml as qy

INTAKE = """\
# Что известно об источниках
sources:
  - { file: source/plan.pdf, note: "лист 08" }

questions:
  # подоконник: на плане нет
  - id: q1
    stage: plan
    target: rooms.r.openings.r_window_1.sill   # окно у балкона
    text: "Высота подоконника?"
    answer: value
    unit: mm
    assumption: 850
  - { id: q2, stage: plan, audience: client, text: "Есть обмер?", answer: text, severity: major }
stages:
  plumbing: { status: absent }
"""

ANSWERS = """\
answers:
  q1: 700 # заказчик 2026-10-29; было 850
  q2: { text: "нет" }
log:
  q1: {"at": "2026-11-04T10:00:00+00:00", "by": "Иван"}
"""


def test_intake_questions_with_their_comments() -> None:
    found = qy.intake_questions(INTAKE)
    assert found is not None
    q1, q2 = found
    assert q1["qid"] == "q1" and q1["kind"] == "value" and q1["assumption"] == 850
    assert q1["note"] == "подоконник: на плане нет\nокно у балкона"
    assert q2["audience"] == "client" and q2["severity"] == "major" and q2["note"] == ""
    assert qy.intake_questions("questions: [") is None  # broken YAML
    assert qy.intake_questions("questions:\n  - { id: q1, stage: plan, text: x }\n") is None


def test_intake_text_keeps_the_base_or_rewrites_only_questions() -> None:
    found = qy.intake_questions(INTAKE)
    assert found is not None
    assert qy.intake_text(INTAKE, found) == INTAKE  # the same data: byte for byte
    changed = [{**found[0], "text": "Подоконник в гостиной?"}, found[1]]
    text = qy.intake_text(INTAKE, changed)
    assert text is not None and text != INTAKE
    assert text.startswith("# Что известно об источниках\nsources:\n")  # the rest stays
    assert "  # подоконник: на плане нет\n  # окно у балкона\n  - id: q1\n" in text
    assert yaml.safe_load(text)["stages"] == {"plumbing": {"status": "absent"}}
    assert qy.intake_questions(text) == changed  # the notes survive a second read
    assert qy.intake_text(INTAKE, []) is not None
    assert yaml.safe_load(qy.intake_text(INTAKE, []) or "")["questions"] == []
    assert qy.intake_text(None, []) is None
    assert qy.intake_text("questions: [", found) == "questions: ["  # broken: as it is
    added = qy.intake_text("sources: []\n", found[1:])
    assert added is not None and qy.intake_questions(added) == found[1:]
    assert qy.intake_text(None, found[1:]) == qy.render_questions(found[1:])


def test_question_notes_need_matching_items() -> None:
    assert qy.question_notes("sources: []\n", ["q1"]) == {}
    assert qy.question_notes(INTAKE, ["q1"]) == {}  # two items, one id: no guessing
    tail = "questions:\n  - { id: a, stage: plan, text: x, severity: minor }\n  # про b\n"
    tail += '  - { id: b, stage: plan, text: "#1", severity: minor }\n'
    assert qy.question_notes(tail, ["a", "b"]) == {"b": "про b"}


def test_answers_round_trip_and_line_edits() -> None:
    entries = qy.answer_entries(ANSWERS)
    assert entries == {
        "q1": (700, {"at": "2026-11-04T10:00:00+00:00", "by": "Иван"}),
        "q2": ({"text": "нет"}, None),
    }
    assert qy.answers_text(ANSWERS, entries) == ANSWERS
    # One answer changed: the comment next to the other one stays
    edited = qy.answers_text(ANSWERS, {**entries, "q2": ({"text": "нет", "resolved": True}, None)})
    assert edited is not None and "q1: 700 # заказчик 2026-10-29; было 850" in edited
    assert qy.answer_entries(edited) == {**entries, "q2": ({"text": "нет", "resolved": True}, None)}
    removed = qy.answers_text(ANSWERS, {"q2": entries["q2"]})
    assert qy.answer_entries(removed or "") == {"q2": entries["q2"]}
    assert qy.answers_text(None, {}) is None
    assert qy.answer_entries(qy.answers_text(None, entries) or "") == entries
    assert qy.answer_entries("answers: [") is None
    assert qy.answer_entries("") == {}
    assert qy.answers_text("answers: [", entries) == "answers: ["


def test_answer_state() -> None:
    assert qy.answer_state(700) == (None, None)
    assert qy.answer_state({"accept": True}) == (None, None)
    assert qy.answer_state({"text": "нет"}) == ("pending", None)
    assert qy.answer_state({"text": "нет", "resolved": True}) == ("resolved", None)
    assert qy.answer_state({"text": "нет", "returned": "Какой?"}) == ("returned", "Какой?")
