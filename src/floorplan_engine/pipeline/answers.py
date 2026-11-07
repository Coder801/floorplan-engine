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
from floorplan_engine.pipeline.variants import save_variant
from floorplan_engine.validation.answers_file import build_digest, edit_answers, parse_answers
from floorplan_engine.validation.issues import (
    VARIANT_FILE,
    Issue,
)
from floorplan_engine.validation.validate import validate_project

MAX_ANSWER_TEXT = 2000


@dataclass
class AnswerSaved:
    """save_answers: why the answer was refused (nothing changed then) and whether the build
    depends on it; blocked_by are other answered questions in the way of the new errors."""

    issues: list[Issue] = field(default_factory=list)
    rebuild: bool = False
    blocked_by: list[Question] = field(default_factory=list)


def _parse_answer(qid: str, raw: Any) -> Answer | Issue | None:
    """An answer from the viewer: a number, a string, a list of groups, {accept: true}, {text};
    None removes it. The analyzer alone marks an answer resolved."""
    path = f"answers.{qid}"
    if raw is None:
        return None
    if isinstance(raw, float) or type(raw) is int:
        return float(raw)
    if isinstance(raw, str):
        return raw.strip() or Issue(ANSWERS_FILE, path, "пустой ответ")
    if isinstance(raw, list) and raw and all(isinstance(g, str) and g for g in raw):
        return list(raw)
    if raw == {"accept": True}:
        return Accept(accept=True)
    if isinstance(raw, dict) and set(raw) == {"text"} and isinstance(raw["text"], str):
        text = raw["text"].strip()
        if not text:
            return Issue(ANSWERS_FILE, path, "пустой ответ")
        if len(text) > MAX_ANSWER_TEXT:
            return Issue(ANSWERS_FILE, path, f"ответ длиннее {MAX_ANSWER_TEXT} символов")
        return TextAnswer(text=text)
    message = "ожидается число, строка, список групп, { accept: true } или { text: ... }"
    return Issue(ANSWERS_FILE, path, message)


def save_answer(project: Path, qid: str, raw: Any, note: AnswerNote | None) -> AnswerSaved:
    """Save one answer from the viewer to answers.yaml (raw None removes it)."""
    return save_answers(project, {qid: raw}, note)


def save_answers(project: Path, items: dict[str, Any], note: AnswerNote | None) -> AnswerSaved:
    """Save answers from the viewer to answers.yaml at once, with one check (None removes an
    answer). If any is refused, the file stays as it was: the model is checked with all of them,
    as the build would. A question may appear only with another answer of the same call (the
    inverter ones with panel_backup), so an id is looked up after the edit. A text answer
    waiting for the analyzer needs no rebuild."""
    path = project / ANSWERS_FILE
    before = validate_project(project)
    old_text = path.read_text("utf-8") if path.exists() else None
    answers = parse_answers(old_text or "") or Answers()
    parsed: dict[str, Answer | None] = {}
    for qid, raw in items.items():
        answer = _parse_answer(qid, raw)
        if isinstance(answer, Issue):
            return AnswerSaved([answer])
        old = answers.answers.get(qid)
        if answer is None and isinstance(old, TextAnswer) and old.resolved:
            message = "ответ уже перенесён в модель: его можно изменить, но не снять"
            return AnswerSaved([Issue(ANSWERS_FILE, f"answers.{qid}", message)])
        parsed[qid] = answer
    new_text = old_text or ""
    for qid, answer in parsed.items():
        new_text = edit_answers(new_text, qid, answer, note)
    path.write_text(new_text, encoding="utf-8")
    after = validate_project(project)
    questions = {q.id for q in [*before.questions, *after.questions]}
    known = {(i.file, i.path) for i in before.errors}
    issues = [
        Issue(ANSWERS_FILE, f"answers.{qid}", f"вопроса «{qid}» нет")
        for qid, answer in parsed.items()
        if answer is not None and qid not in questions
    ] or [i for i in after.errors if (i.file, i.path) not in known]
    if issues:
        if old_text is None:
            path.unlink()
        else:
            path.write_text(old_text, encoding="utf-8")
        blocked = [
            q
            for q in before.questions
            if q.id not in parsed
            and q.id in answers.answers
            and q.target is not None
            and any(q.target.split(".")[-1] in i.message for i in issues)
        ]
        return AnswerSaved(issues, blocked_by=blocked)
    return AnswerSaved(rebuild=build_digest(old_text) != build_digest(new_text))


def save_wizard(
    project: Path,
    variant: dict[str, Any] | None,
    items: dict[str, Any],
    note: AnswerNote | None,
) -> AnswerSaved:
    """The setup wizard: a wiring variant and answers together, for one rebuild. If the answers
    are refused, variant.yaml goes back too: either everything is saved or nothing is."""
    path = project / VARIANT_FILE
    old_variant = path.read_text("utf-8") if path.exists() else None
    if variant is not None:
        issues = save_variant(project, variant)
        if issues:
            return AnswerSaved(issues)
    saved = save_answers(project, items, note) if items else AnswerSaved()
    if saved.issues and variant is not None:
        if old_variant is None:
            path.unlink()
        else:
            path.write_text(old_variant, encoding="utf-8")
    saved.rebuild = not saved.issues and (saved.rebuild or variant is not None)
    return saved
