"""Answers from the viewer: a value is checked before it goes into answers.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from floorplan_engine.model.intake import (
    ANSWERS_FILE,
    Accept,
    Answer,
    AnswerNote,
    Answers,
    Question,
    TextAnswer,
)
from floorplan_engine.validation.answers_file import build_digest, edit_answers, parse_answers
from floorplan_engine.validation.issues import (
    Issue,
)
from floorplan_engine.validation.validate import validate_project

MAX_ANSWER_TEXT = 2000


@dataclass
class AnswerSaved:
    """save_answer: why the answer was refused (nothing changed then) and whether the build
    depends on it; blocked_by are other answered questions in the way of the new errors."""

    issues: list[Issue] = field(default_factory=list)
    rebuild: bool = False
    blocked_by: list[Question] = field(default_factory=list)


def _parse_answer(qid: str, raw: Any) -> Answer | Issue | None:
    """An answer from the viewer: a number, a string, {accept: true}, {text}; None removes it.
    The analyzer alone marks an answer resolved."""
    path = f"answers.{qid}"
    if raw is None:
        return None
    if isinstance(raw, float) or type(raw) is int:
        return float(raw)
    if isinstance(raw, str):
        return raw.strip() or Issue(ANSWERS_FILE, path, "пустой ответ")
    if raw == {"accept": True}:
        return Accept(accept=True)
    if isinstance(raw, dict) and set(raw) == {"text"} and isinstance(raw["text"], str):
        text = raw["text"].strip()
        if not text:
            return Issue(ANSWERS_FILE, path, "пустой ответ")
        if len(text) > MAX_ANSWER_TEXT:
            return Issue(ANSWERS_FILE, path, f"ответ длиннее {MAX_ANSWER_TEXT} символов")
        return TextAnswer(text=text)
    return Issue(ANSWERS_FILE, path, "ожидается число, строка, { accept: true } или { text: ... }")


def save_answer(project: Path, qid: str, raw: Any, note: AnswerNote | None) -> AnswerSaved:
    """Save one answer from the viewer to answers.yaml (raw None removes it). An answer that
    brings new errors is refused and the file stays as it was: the model is checked with it, as
    the build would. A text answer waiting for the analyzer needs no rebuild."""
    path = project / ANSWERS_FILE
    before = validate_project(project)
    old_text = path.read_text("utf-8") if path.exists() else None
    if not any(q.id == qid for q in before.questions):
        return AnswerSaved([Issue(ANSWERS_FILE, f"answers.{qid}", f"вопроса «{qid}» нет")])
    answer = _parse_answer(qid, raw)
    if isinstance(answer, Issue):
        return AnswerSaved([answer])
    answers = parse_answers(old_text or "") or Answers()
    old = answers.answers.get(qid)
    if answer is None and isinstance(old, TextAnswer) and old.resolved:
        message = "ответ уже перенесён в модель: его можно изменить, но не снять"
        return AnswerSaved([Issue(ANSWERS_FILE, f"answers.{qid}", message)])
    new_text = edit_answers(old_text or "", qid, answer, note)
    path.write_text(new_text, encoding="utf-8")
    after = validate_project(project)
    known = {(i.file, i.path) for i in before.errors}
    issues = [i for i in after.errors if (i.file, i.path) not in known]
    if issues:
        if old_text is None:
            path.unlink()
        else:
            path.write_text(old_text, encoding="utf-8")
        blocked = [
            q
            for q in before.questions
            if q.id != qid
            and q.id in answers.answers
            and q.target is not None
            and any(q.target.split(".")[-1] in i.message for i in issues)
        ]
        return AnswerSaved(issues, blocked_by=blocked)
    return AnswerSaved(rebuild=build_digest(old_text) != build_digest(new_text))
