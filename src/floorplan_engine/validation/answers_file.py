"""answers.yaml as a file: what the viewer writes and what a build depends on.

The answer entries are edited line by line, so the comments people left next to them stay
(`q1: 700 # заказчик 2026-10-29; было 850`). Who answered and when goes to the `log` section.
A text answer waiting for the analyzer changes nothing in a build: it is outside build_digest, and
its question state is taken from the answers, not from the report (with_pending_text).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import yaml
from pydantic import ValidationError

from floorplan_engine.model.intake import Answer, AnswerNote, Answers, TextAnswer


def parse_answers(text: str) -> Answers | None:
    """The answers of a file's text; None if the file is broken (the check reports that)."""
    try:
        return Answers.model_validate(yaml.safe_load(text) or {})
    except (yaml.YAMLError, ValidationError):
        return None


def _plain(answer: Answer) -> object:
    return (
        answer.model_dump(exclude_defaults=True) if not isinstance(answer, float | str) else answer
    )


def dump_answers(answers: Answers) -> str:
    """The whole file from the model: comments are lost, the log stays."""
    data: dict[str, Any] = {"answers": {k: _plain(v) for k, v in answers.answers.items()}}
    if answers.log:
        data["log"] = {k: v.model_dump(exclude_none=True) for k, v in answers.log.items()}
    return yaml.safe_dump(data, allow_unicode=True)


def pending_text(answer: object) -> bool:
    """A text answer the analyzer has not handled yet: plain data or a model."""
    if isinstance(answer, TextAnswer):
        return not answer.resolved
    return isinstance(answer, dict) and "text" in answer and not answer.get("resolved")


def build_digest(text: str | None) -> str:
    """Digest of the answers a build depends on: without pending text answers and the log. A broken
    file gives the digest of its text: it differs from any built state."""
    answers = parse_answers(text or "")
    if answers is None:
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]
    kept = {k: _plain(v) for k, v in answers.answers.items() if not pending_text(v)}
    data = json.dumps(kept, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


def with_pending_text(
    report: dict[str, Any] | None, answers: dict[str, Any]
) -> dict[str, Any] | None:
    """The report with question states after text answers saved since the build: such an answer
    does not rebuild the project, so the state in the report may be behind."""
    if report is None:
        return None
    questions = []
    for q in report.get("questions", []):
        answer = answers.get(q.get("id"))
        state = q.get("state")
        if pending_text(answer):
            state = "text"
        elif answer is None and state == "text":
            state = "open"
        questions.append({**q, "state": state})
    return {**report, "questions": questions}


def _flow(value: object) -> str:
    """One line of YAML: JSON is YAML, and it quotes `yes` and keeps line breaks in the string."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return json.dumps(value, ensure_ascii=False)


def _comment(line: str) -> str:
    """The trailing comment of a YAML line with its leading spaces, "" if there is none."""
    quote = ""
    for k, ch in enumerate(line):
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and k > 0 and line[k - 1] == " ":
            return " " + line[k:]
    return ""


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _set_entry(text: str, section: str, key: str, value: str | None) -> str:
    """The `key: value` line in a top-level section; value None removes the entry."""
    lines = text.splitlines()
    head = next(
        (k for k, s in enumerate(lines) if re.fullmatch(rf"{section}:(\s*\{{\}})?\s*(#.*)?", s)),
        None,
    )
    if head is None:
        if value is None:
            return text
        lines.append(f"{section}:")
        head = len(lines) - 1
    lines[head] = lines[head].replace("{}", "").rstrip()
    end = next(
        (k for k in range(head + 1, len(lines)) if lines[k] and lines[k][0] not in " #"),
        len(lines),
    )
    pattern = re.compile(rf"\s+{re.escape(key)}\s*:")
    start = next((k for k in range(head + 1, end) if pattern.match(lines[k])), None)
    if start is not None:
        stop = start + 1
        while stop < end and (not lines[stop] or _indent(lines[stop]) > _indent(lines[start])):
            stop += 1
        single = stop == start + 1
        new = (
            []
            if value is None
            else [
                f"{' ' * _indent(lines[start])}{key}: {value}"
                + (_comment(lines[start]) if single else "")
            ]
        )
        lines[start:stop] = new
        end += len(new) - (stop - start)
    elif value is not None:
        last = next(
            (k for k in range(end - 1, head, -1) if lines[k].strip() and lines[k][0] == " "), head
        )
        indent = _indent(lines[last]) if last > head else 2
        lines.insert(last + 1, f"{' ' * indent}{key}: {value}")
    if not any(s.strip() and s[0] == " " for s in lines[head + 1 : end + 1]):
        lines[head] = f"{section}: {{}}"
    return "\n".join(lines) + "\n"


def edit_answers(text: str, qid: str, answer: Answer | None, note: AnswerNote | None) -> str:
    """The file's text with the answer to qid set (None removes it and its log entry). Everything
    else in the file stays; if the file is written in a way the line edit cannot follow, it is
    written anew from the model, so the answer is never lost."""
    current = parse_answers(text) or Answers()
    answers = {k: v for k, v in current.answers.items() if k != qid}
    log = {k: v for k, v in current.log.items() if k != qid}
    if answer is not None:
        answers[qid] = answer
        if note is not None:
            log[qid] = note
    expected = Answers(answers=answers, log=log)
    edited = _set_entry(text, "answers", qid, None if answer is None else _flow(_plain(answer)))
    logged = None if answer is None or note is None else note.model_dump(exclude_none=True)
    edited = _set_entry(edited, "log", qid, None if logged is None else _flow(logged))
    return edited if parse_answers(edited) == expected else dump_answers(expected)
