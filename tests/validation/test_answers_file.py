"""answers.yaml as a file: line edits keep comments, the digest ignores what a build ignores."""

from __future__ import annotations

from floorplan_engine.model.intake import Accept, AnswerNote, Answers, TextAnswer
from floorplan_engine.validation.answers_file import (
    build_digest,
    dump_answers,
    edit_answers,
    parse_answers,
    with_pending_text,
)

FILE = """answers:
  q1: 700 # подоконник (заказчик 2026-10-29; было 850)
  q2: { text: "Своя линия # автомат", resolved: true }
"""
NOTE = AnswerNote(at="2026-11-04T10:00:00+00:00", by="Иван")


def _parsed(text: str) -> Answers:
    answers = parse_answers(text)
    assert answers is not None
    return answers


def test_change_keeps_comment_and_other_lines() -> None:
    text = edit_answers(FILE, "q1", 800.0, NOTE)
    assert "  q1: 800 # подоконник (заказчик 2026-10-29; было 850)\n" in text
    assert '  q2: { text: "Своя линия # автомат", resolved: true }\n' in text
    assert _parsed(text).log["q1"] == NOTE


def test_new_answer_goes_after_the_last_one() -> None:
    text = edit_answers(FILE, "q3", Accept(accept=True), None)
    assert text.splitlines()[-1] == '  q3: {"accept": true}'
    assert edit_answers("", "q1", TextAnswer(text="т"), None) == 'answers:\n  q1: {"text": "т"}\n'
    assert _parsed(text).answers["q3"] == Accept(accept=True)
    assert "log" not in text


def test_quoted_values_stay_strings() -> None:
    """`yes` written bare would be read as true."""
    answers = _parsed(edit_answers("", "panel_npe", "yes", None))
    assert answers.answers == {"panel_npe": "yes"}
    assert _parsed(edit_answers("", "q1", TextAnswer(text="а\nб"), None)).answers["q1"] == (
        TextAnswer(text="а\nб")
    )


def test_remove_answer_and_its_log() -> None:
    text = edit_answers(edit_answers(FILE, "q1", 800.0, NOTE), "q1", None, None)
    assert "q1" not in text
    assert _parsed(text).answers.keys() == {"q2"}
    assert _parsed(text).log == {}


def test_removing_the_last_answer_leaves_a_valid_file() -> None:
    text = edit_answers("answers:\n  q1: 700\n", "q1", None, None)
    assert _parsed(text) == Answers()


def test_answers_after_empty_section_and_multiline_entry() -> None:
    assert _parsed(edit_answers("answers: {}\n", "q1", 700.0, None)).answers == {"q1": 700.0}
    dumped = dump_answers(Answers(answers={"q1": TextAnswer(text="длинный " * 30), "q2": 5.0}))
    text = edit_answers(dumped, "q1", TextAnswer(text="коротко"), None)
    assert _parsed(text).answers == {"q1": TextAnswer(text="коротко"), "q2": 5.0}


def test_unusual_file_is_rewritten_without_losing_answers() -> None:
    text = edit_answers('{"answers": {"q1": 700}}\n', "q2", 5.0, None)
    assert _parsed(text).answers == {"q1": 700.0, "q2": 5.0}


def test_digest_ignores_pending_text_log_and_comments() -> None:
    base = build_digest("answers:\n  q1: 700\n")
    assert build_digest("answers:\n  q1: 700 # c\n") == base
    assert (
        build_digest(edit_answers("answers:\n  q1: 700\n", "q2", TextAnswer(text="т"), NOTE))
        == base
    )
    assert build_digest("answers:\n  q1: 800\n") != base
    assert build_digest("answers:\n  q1: 700\n  q2: { text: т, resolved: true }\n") != base
    assert build_digest('answers:\n  q1: 700\n  q2: { text: т, returned: "где?" }\n') == base
    assert build_digest("answers:\n  q1: 700\n  q2: { accept: true }\n") != base
    assert build_digest(None) == build_digest("")
    assert build_digest("answers: [") != build_digest("answers: {")


def test_pending_text_overrides_report_state() -> None:
    report = {
        "questions": [
            {"id": "q1", "state": "open"},
            {"id": "q2", "state": "text"},
            {"id": "q3", "state": "answered"},
            {"id": "q4", "state": "text"},
            {"id": "q5", "state": "text"},
            {"id": "q6", "state": "returned"},
        ]
    }
    answers = {
        "q1": {"text": "т"},
        "q3": {"text": "т", "resolved": True},
        "q4": {"text": "т"},
        "q5": {"text": "т", "returned": "где?"},
    }
    shown = with_pending_text(report, answers)
    assert shown is not None
    assert [q["state"] for q in shown["questions"]] == [
        "text",
        "open",
        "answered",
        "text",
        "returned",
        "open",
    ]
    assert with_pending_text(None, {}) is None
