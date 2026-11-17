"""Questions and answers as YAML text (docs/database.md, «Вопросы и ответы»): what the database
tables are read from (intake.yaml, answers.yaml of a model version) and written back to. No
database here: plain data in, text out, so the migration that fills the tables uses it too.

- A question is its definition (stage, target, kind of answer, options… — the `question` row) and
  its wording (text, assumption, severity and the YAML comment next to it — a
  `question_revision`). The comment is kept as `note`, so writing the question again does not lose
  it.
- An answer is its value as in answers.yaml with its `log` entry (an `answer_revision`).
- Text from the tables keeps the base text (the model version's file) where it says the same:
  equal data give the base back byte for byte, a changed answer is edited line by line
  (answers_file.edit_answers keeps the comments), changed questions rewrite only the `questions`
  section of intake.yaml.
"""

from __future__ import annotations

import json
import re
from typing import Any

import yaml
from pydantic import ValidationError

from floorplan_engine.model.intake import Answers, Intake, Question
from floorplan_engine.validation.answers_file import edit_answers, parse_answers

# Columns of the question row (its definition) and of a question revision (its wording)
DEFINITION = ("stage", "target", "also", "unit", "audience", "kind", "options", "option_labels")
WORDING = ("text", "assumption", "severity", "note")


def parsed_copy(text: str) -> Any:
    """The jsonb copy of a YAML text: dates and other non-JSON values become strings; a file that
    does not parse is kept as None (the text is the truth, the check reports the error)."""
    try:
        return json.loads(json.dumps(yaml.safe_load(text), default=str))
    except yaml.YAMLError:
        return None


# --- intake.yaml ----------------------------------------------------------------------------


def _intake(text: str) -> Intake | None:
    try:
        return Intake.model_validate(yaml.safe_load(text) or {})
    except (yaml.YAMLError, ValidationError):
        return None


def to_fields(question: Question, note: str = "") -> dict[str, Any]:
    """A question of intake.yaml as the columns of its row and revision (plus qid)."""
    data = question.model_dump(mode="json")
    return {
        "qid": question.id,
        **{k: data[k] for k in DEFINITION if k != "kind"},
        "kind": question.answer,
        **{k: data[k] for k in WORDING if k != "note"},
        "note": note,
    }


def from_fields(fields: dict[str, Any]) -> Question:
    """The question of intake.yaml from the columns of its row and revision."""
    data = {k: fields.get(k) for k in (*DEFINITION, *WORDING) if k not in ("kind", "note")}
    clean = {k: v for k, v in data.items() if v not in (None, [], {})}
    return Question.model_validate({**clean, "id": fields["qid"], "answer": fields["kind"]})


def intake_questions(text: str) -> list[dict[str, Any]] | None:
    """The questions of an intake.yaml text in their order, as fields (to_fields) with the comments
    next to each; None if the file is broken or invalid (the check reports that, the tables keep
    the last good state)."""
    intake = _intake(text)
    if intake is None:
        return None
    notes = question_notes(text, [q.id for q in intake.questions])
    return [to_fields(q, notes.get(q.id, "")) for q in intake.questions]


def _comment(line: str) -> str:
    """The comment of a YAML line without `#`, "" if there is none (a `#` inside quotes is text)."""
    quote = ""
    for k, ch in enumerate(line):
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (k == 0 or line[k - 1] in " \t"):
            return line[k + 1 :].strip()
    return ""


def _section(lines: list[str], name: str) -> tuple[int, int] | None:
    """Lines of a top-level section: (its header, the first line after it)."""
    head = next((k for k, s in enumerate(lines) if re.match(rf"{name}\s*:", s)), None)
    if head is None:
        return None
    end = next(
        (k for k in range(head + 1, len(lines)) if lines[k] and lines[k][0] not in " #\t-"),
        len(lines),
    )
    return head, end


def question_notes(text: str, ids: list[str]) -> dict[str, str]:
    """The YAML comments of each question: the comment lines above its `- ` and the comments at
    the end of its lines, one per line. Matched to ids by order; a section the lines do not follow
    gives no notes."""
    lines = text.splitlines()
    bounds = _section(lines, "questions")
    if bounds is None:
        return {}
    head, end = bounds
    starts = [k for k in range(head + 1, end) if re.match(r"\s*- ", lines[k])]
    if starts:
        indent = min(len(lines[k]) - len(lines[k].lstrip()) for k in starts)
        starts = [k for k in starts if len(lines[k]) - len(lines[k].lstrip()) == indent]
    if len(starts) != len(ids):
        return {}
    notes: dict[str, str] = {}
    previous = head + 1
    for n, (qid, start) in enumerate(zip(ids, starts, strict=True)):
        stop = starts[n + 1] if n + 1 < len(starts) else end
        above = [
            _comment(s) for s in lines[previous:start] if s.strip().startswith("#") and _comment(s)
        ]
        own = [s for s in lines[start:stop] if not s.strip().startswith("#")]
        inline = [c for c in (_comment(s) for s in own) if c]
        # Comment lines at the end of an item belong to the next one
        tail = stop
        while tail > start + 1 and (
            not lines[tail - 1].strip() or lines[tail - 1].strip()[0] == "#"
        ):
            tail -= 1
        previous = tail
        found = [*above, *inline]
        if found:
            notes[qid] = "\n".join(found)
    return notes


def _plain_number(value: Any) -> Any:
    return int(value) if isinstance(value, float) and value.is_integer() else value


def render_questions(questions: list[dict[str, Any]]) -> str:
    """The `questions` section from fields, the notes as comment lines above each question."""
    if not questions:
        return "questions: []\n"
    out = ["questions:"]
    for fields in questions:
        data = from_fields(fields).model_dump(mode="json", exclude_defaults=True)
        data = {k: _plain_number(v) for k, v in data.items()}
        out += [f"  # {line}" for line in str(fields.get("note") or "").splitlines()]
        item = yaml.safe_dump([data], allow_unicode=True, sort_keys=False, width=10_000)
        out += [f"  {line}" for line in item.splitlines()]
    return "\n".join(out) + "\n"


def intake_text(base: str | None, questions: list[dict[str, Any]]) -> str | None:
    """intake.yaml with these questions: the base text if it says the same (comments, order and
    quotes stay), otherwise the base with its `questions` section written anew. A broken base is
    given back as it is (the check reports it). No base and no questions — no file."""
    if base is None:
        return render_questions(questions) if questions else None
    intake = _intake(base)
    if intake is None:
        return base
    wanted = [from_fields(f) for f in questions]
    notes = question_notes(base, [q.id for q in intake.questions])
    current = [to_fields(q, notes.get(q.id, "")) for q in intake.questions]
    if intake.questions == wanted and [f["note"] for f in current] == [
        f.get("note") or "" for f in questions
    ]:
        return base
    lines = base.splitlines()
    bounds = _section(lines, "questions")
    section = render_questions(questions).splitlines()
    if bounds is None:
        lines += section
    else:
        lines[bounds[0] : bounds[1]] = section
    return "\n".join(lines) + "\n"


# --- answers.yaml ---------------------------------------------------------------------------


def answer_entries(text: str) -> dict[str, tuple[Any, dict[str, Any] | None]] | None:
    """The answers of an answers.yaml text: qid → (value as written, log entry or None), in file
    order; None if the file is broken or invalid."""
    answers = parse_answers(text)
    raw = parsed_copy(text)
    if answers is None or not isinstance(raw, dict):
        return None if answers is None else {}
    values = raw.get("answers") or {}
    log = raw.get("log") or {}
    return {qid: (values[qid], log.get(qid)) for qid in answers.answers}


def answer_state(value: Any) -> tuple[str | None, str | None]:
    """State and studio comment of an answer value: a text answer waits (pending), is taken into
    account (resolved) or sent back with a comment (returned); other answers have no state."""
    if not isinstance(value, dict) or "text" not in value:
        return None, None
    if value.get("resolved"):
        return "resolved", None
    if value.get("returned"):
        return "returned", str(value["returned"])
    return "pending", None


def _answers(entries: dict[str, tuple[Any, dict[str, Any] | None]]) -> Answers:
    return Answers.model_validate(
        {
            "answers": {qid: value for qid, (value, _) in entries.items()},
            "log": {qid: log for qid, (_, log) in entries.items() if log is not None},
        }
    )


def answers_text(
    base: str | None, entries: dict[str, tuple[Any, dict[str, Any] | None]]
) -> str | None:
    """answers.yaml with these answers and log entries: the base text if it says the same,
    otherwise the base edited line by line (comments next to other answers stay). A broken base is
    given back as it is. No base and no answers — no file."""
    if base is None and not entries:
        return None
    current = parse_answers(base or "")
    if current is None:
        return base
    wanted = _answers(entries)
    if base is not None and current == wanted:
        return base
    text = base or ""
    for qid in [*current.answers, *(q for q in wanted.answers if q not in current.answers)]:
        answer = wanted.answers.get(qid)
        note = wanted.log.get(qid)
        if answer == current.answers.get(qid) and note == current.log.get(qid):
            continue
        text = edit_answers(text, qid, answer, note)
    return text
