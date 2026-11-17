"""Questions and answers in the database (docs/database.md, «Вопросы и ответы»; decision
2026-11-17): the tables question, question_revision and answer_revision are the truth, intake.yaml
and answers.yaml are the exchange format at the border — a build, the analyzer, `project push` and
`pull`.

- Every new model version is read into the tables (ingest, from repositories.add_model_version): a
  new qid — a question; a changed wording or definition — a question revision; a question gone
  from intake.yaml — a revision `removed`; a changed answer or log entry — an answer revision; an
  answer gone — a revision with no value. Then the version's intake.yaml and answers.yaml are made
  from the tables (texts): the same text, unless the tables say otherwise.
- A build writes the code-built questions (panel_…, heating_…) with source `code` (record_code):
  they are never written in intake.yaml, but keep their history.
- The texts of the latest version are made from the tables before a build and on pull
  (project_store.project_files).
- backfill: the migration fills the tables from the existing model versions, in order.

Who: the model version's author (analyzer | operator | user), its user, and the label of a client
code or a name from the `log` of answers.yaml. Functions take an open Session and do not commit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from floorplan_engine.model.intake import ANSWERS_FILE, INTAKE_FILE
from floorplan_engine.service.db import questions_yaml as qy
from floorplan_engine.service.db.models import (
    AnswerRevision,
    Build,
    ModelVersion,
    Question,
    QuestionRevision,
    now,
)
from floorplan_engine.validation.answers import AUTO_PREFIXES

# Who added a question, by the author of the model version it came with
SOURCE_OF = {"analyzer": "analyzer", "operator": "operator", "user": "studio", "code": "code"}
CODE = "code"


@dataclass(frozen=True)
class Author:
    kind: str  # analyzer | operator | user | code
    user_id: uuid.UUID | None = None
    label: str = ""  # a client code («код: Иван») or a name


@dataclass
class Current:
    """A question with its latest wording and answer revisions (None — none yet)."""

    row: Question
    wording: QuestionRevision | None
    answer: AnswerRevision | None

    @property
    def in_intake(self) -> bool:
        return self.row.position is not None and self.wording is not None

    def fields(self) -> dict[str, Any]:
        """The question as qy.to_fields gives it."""
        w = self.wording
        return {
            "qid": self.row.qid,
            **{k: getattr(self.row, k) for k in qy.DEFINITION},
            **{k: getattr(w, k) if w is not None else None for k in qy.WORDING},
            "note": w.note if w is not None else "",
        }


def current(session: Session, project_id: uuid.UUID) -> dict[str, Current]:
    """The project's questions by qid, with their latest revisions."""
    rows = session.scalars(select(Question).where(Question.project_id == project_id)).all()
    ids = [r.id for r in rows]
    wordings = {
        w.question_id: w
        for w in session.scalars(
            select(QuestionRevision)
            .where(QuestionRevision.question_id.in_(ids))
            .ext(distinct_on(QuestionRevision.question_id))
            .order_by(QuestionRevision.question_id, QuestionRevision.number.desc())
        )
    }
    answers = {
        a.question_id: a
        for a in session.scalars(
            select(AnswerRevision)
            .where(AnswerRevision.question_id.in_(ids))
            .ext(distinct_on(AnswerRevision.question_id))
            .order_by(AnswerRevision.question_id, AnswerRevision.number.desc())
        )
    }
    return {r.qid: Current(r, wordings.get(r.id), answers.get(r.id)) for r in rows}


def history(
    session: Session, question: Question
) -> tuple[list[QuestionRevision], list[AnswerRevision]]:
    """All revisions of a question, oldest first: its wording and its answers."""
    wordings = session.scalars(
        select(QuestionRevision)
        .where(QuestionRevision.question_id == question.id)
        .order_by(QuestionRevision.number)
    ).all()
    answers = session.scalars(
        select(AnswerRevision)
        .where(AnswerRevision.question_id == question.id)
        .order_by(AnswerRevision.number)
    ).all()
    return list(wordings), list(answers)


def _row(session: Session, project_id: uuid.UUID, qid: str, source: str) -> Question:
    row = Question(
        project_id=project_id,
        qid=qid,
        source=source,
        also=[],
        audience="studio",
        kind="text",
        options=[],
        option_labels={},
    )
    session.add(row)
    session.flush()
    return row


def _next(previous: QuestionRevision | AnswerRevision | None) -> int:
    return previous.number + 1 if previous is not None else 1


@dataclass(frozen=True)
class _Stamp:
    """Who and when, and in which model version, for a new revision."""

    author: Author
    at: datetime
    version_id: uuid.UUID | None


def _word(
    session: Session, c: Current, fields: dict[str, Any], reason: str, stamp: _Stamp
) -> QuestionRevision:
    revision = QuestionRevision(
        question_id=c.row.id,
        number=_next(c.wording),
        text=fields.get("text") or "",
        assumption=fields.get("assumption"),
        severity=fields.get("severity"),
        note=fields.get("note") or "",
        reason=reason,
        author=stamp.author.kind,
        user_id=stamp.author.user_id,
        author_label=stamp.author.label,
        model_version_id=stamp.version_id,
        created_at=stamp.at,
    )
    session.add(revision)
    c.wording = revision
    return revision


def _define(row: Question, fields: dict[str, Any]) -> bool:
    """Set the definition columns; True if any changed."""
    changed = False
    for key in qy.DEFINITION:
        if getattr(row, key) != fields[key]:
            setattr(row, key, fields[key])
            changed = True
    return changed


def _same_wording(c: Current, fields: dict[str, Any]) -> bool:
    w = c.wording
    return (
        w is not None
        and all(getattr(w, k) == fields.get(k) for k in ("text", "assumption", "severity"))
        and w.note == (fields.get("note") or "")
    )


def read_questions(
    session: Session,
    project_id: uuid.UUID,
    questions: list[dict[str, Any]],
    stamp: _Stamp,
) -> None:
    """The questions of an intake.yaml (qy.intake_questions) into the tables."""
    cur = current(session, project_id)
    seen = set()
    for position, fields in enumerate(questions):
        qid = fields["qid"]
        seen.add(qid)
        c = cur.get(qid)
        if c is None:
            c = Current(
                _row(session, project_id, qid, SOURCE_OF.get(stamp.author.kind, CODE)), None, None
            )
        removed = c.wording is not None and c.wording.reason == "removed"
        defined = _define(c.row, fields)
        c.row.position = position
        if c.wording is None:
            _word(session, c, fields, "new", stamp)
        elif removed:
            _word(session, c, fields, "restored", stamp)
        elif defined or not _same_wording(c, fields):
            _word(session, c, fields, "edit", stamp)
    for qid, c in cur.items():
        if qid not in seen and c.in_intake:
            c.row.position = None
            _word(session, c, c.fields(), "removed", stamp)


def _label(previous: AnswerRevision | None, log: dict[str, Any] | None, author: Author) -> str:
    """Who gave this answer by the log of answers.yaml: the reviewer if the review is new, the one
    who answered if the answer is; an unchanged log entry names someone else's answer — no one."""
    if author.label:
        return author.label
    before = previous.log if previous is not None and isinstance(previous.log, dict) else {}
    if not isinstance(log, dict) or log == before:
        return ""
    if log.get("reviewed_at") and log.get("reviewed_at") != before.get("reviewed_at"):
        return str(log.get("reviewed_by") or "")
    return str(log.get("by") or "")


def _answer(
    session: Session,
    c: Current,
    value: Any,
    log: dict[str, Any] | None,
    stamp: _Stamp,
) -> None:
    state, comment = qy.answer_state(value)
    revision = AnswerRevision(
        question_id=c.row.id,
        number=_next(c.answer),
        value=value,
        state=state,
        comment=comment,
        log=log,
        author=stamp.author.kind,
        user_id=stamp.author.user_id,
        author_label=_label(c.answer, log, stamp.author),
        model_version_id=stamp.version_id,
        created_at=stamp.at,
    )
    session.add(revision)
    c.answer = revision


def read_answers(
    session: Session,
    project_id: uuid.UUID,
    entries: dict[str, tuple[Any, dict[str, Any] | None]],
    stamp: _Stamp,
) -> None:
    """The answers of an answers.yaml (qy.answer_entries) into the tables. An answer to a qid
    with no question yet (a code-built one before its first build, or a stale answer) gets a row
    of its own, not written in intake.yaml."""
    cur = current(session, project_id)
    for qid, (value, log) in entries.items():
        c = cur.get(qid)
        if c is None:
            source = (
                CODE if qid.startswith(AUTO_PREFIXES) else SOURCE_OF.get(stamp.author.kind, CODE)
            )
            c = cur[qid] = Current(_row(session, project_id, qid, source), None, None)
        if c.answer is not None and c.answer.value == value and c.answer.log == log:
            continue
        _answer(session, c, value, log, stamp)
    for qid, c in cur.items():
        if qid not in entries and c.answer is not None and c.answer.value is not None:
            _answer(session, c, None, None, stamp)


def _read(
    session: Session,
    project_id: uuid.UUID,
    intake: str | None,
    answers: str | None,
    stamp: _Stamp,
) -> None:
    """A version's intake.yaml and answers.yaml into the tables; a broken or invalid file is
    skipped (the check reports it, the tables keep the last good state); no file — nothing."""
    questions = [] if intake is None else qy.intake_questions(intake)
    if questions is not None:
        read_questions(session, project_id, questions, stamp)
    entries = {} if answers is None else qy.answer_entries(answers)
    if entries is not None:
        read_answers(session, project_id, entries, stamp)
    session.flush()


def texts(session: Session, project_id: uuid.UUID, base: ModelVersion) -> dict[str, str | None]:
    """intake.yaml and answers.yaml from the tables (None — no file); the version's own texts give
    the comments and the layout (questions_yaml.intake_text, answers_text)."""
    cur = current(session, project_id)
    asked = sorted((c for c in cur.values() if c.in_intake), key=lambda c: c.row.position or 0)
    answered = sorted(
        (c for c in cur.values() if c.answer is not None and c.answer.value is not None),
        key=lambda c: (c.answer.created_at if c.answer is not None else now(), c.row.qid),
    )
    entries = {c.row.qid: (c.answer.value, c.answer.log) for c in answered if c.answer is not None}
    return {
        INTAKE_FILE: qy.intake_text(base.intake_yaml, [c.fields() for c in asked]),
        ANSWERS_FILE: qy.answers_text(base.answers_yaml, entries),
    }


COLUMNS = {INTAKE_FILE: "intake_yaml", ANSWERS_FILE: "answers_yaml"}


def snapshot(session: Session, version: ModelVersion) -> None:
    """The version's intake.yaml and answers.yaml (and their jsonb copies) as the tables make
    them."""
    data = dict(version.data or {})
    for name, text in texts(session, version.project_id, version).items():
        column = COLUMNS[name]
        if getattr(version, column) == text:
            continue
        setattr(version, column, text)
        if text is None:
            data.pop(name, None)
        else:
            data[name] = qy.parsed_copy(text)
    version.data = data


def ingest(session: Session, version: ModelVersion, author: Author) -> None:
    """A new model version into the tables, then its texts from them (snapshot)."""
    stamp = _Stamp(author, version.created_at or now(), version.id)
    _read(session, version.project_id, version.intake_yaml, version.answers_yaml, stamp)
    snapshot(session, version)
    session.flush()


def record_code(
    session: Session, project_id: uuid.UUID, version_id: uuid.UUID | None, report: dict[str, Any]
) -> None:
    """The code-built questions of a build report (id panel_…, heating_…) with source `code`: a
    row when one is new, a revision when its wording or definition changed."""
    cur = current(session, project_id)
    stamp = _Stamp(Author(CODE), now(), version_id)
    for q in report.get("questions") or []:
        qid = q.get("id") if isinstance(q, dict) else None
        if not isinstance(qid, str) or not qid.startswith(AUTO_PREFIXES):
            continue
        fields = {
            "qid": qid,
            "stage": q.get("stage"),
            "target": q.get("target"),
            "also": q.get("also") or [],
            "unit": q.get("unit"),
            "audience": q.get("audience") or "studio",
            "kind": q.get("answer") or "text",
            "options": q.get("options") or [],
            "option_labels": q.get("option_labels") or {},
            "text": q.get("text") or "",
            "assumption": q.get("assumption"),
            "severity": q.get("severity"),
            "note": "",
        }
        c = cur.get(qid)
        if c is None:
            c = cur[qid] = Current(_row(session, project_id, qid, CODE), None, None)
        defined = _define(c.row, fields)
        if c.wording is None:
            _word(session, c, fields, "new", stamp)
        elif defined or not _same_wording(c, fields):
            _word(session, c, fields, "edit", stamp)
    session.flush()


def backfill(session: Session) -> int:
    """Fill the empty tables from the existing model versions of every project, in version order
    (migration 0017): the author of each version, the labels from the `log` of answers.yaml, the
    time of the version; the code-built questions from the newest build of each version. Projects
    that already have questions are skipped. Returns the number of versions read."""
    done = set(session.scalars(select(Question.project_id).distinct()))
    # Only these columns: the migration runs this with the schema of its time
    query = select(
        ModelVersion.id,
        ModelVersion.project_id,
        ModelVersion.intake_yaml,
        ModelVersion.answers_yaml,
        ModelVersion.author,
        ModelVersion.user_id,
        ModelVersion.created_at,
    ).order_by(ModelVersion.project_id, ModelVersion.version)
    if done:
        query = query.where(ModelVersion.project_id.not_in(done))
    rows = session.execute(query).all()
    for vid, project_id, intake, answers, author, user_id, created_at in rows:
        stamp = _Stamp(Author(author, user_id), created_at, vid)
        _read(session, project_id, intake, answers, stamp)
        report = session.scalar(
            select(Build.report)
            .where(Build.model_version_id == vid)
            .order_by(Build.created_at.desc())
            .limit(1)
        )
        if isinstance(report, dict):
            record_code(session, project_id, vid, report)
    return len(rows)
