"""Question threads (docs/question-threads.md; migration 0022): a question is discussed in a
thread — messages of the one asked and of the studio, one of which the studio accepts as the
answer. The tables question_thread and thread_message; the YAML at the border (intake.yaml,
answers.yaml) does not know about threads and is made from the question tables as before.

- Every new question gets an open thread (follow, from questions.ingest and record_code); one open
  or checking thread per question (a partial unique index).
- The answers of a model version follow into its threads (follow): a form answer (a value, a
  choice, groups of the panel, accept) resolves the open thread, a removed one opens it again; a
  text answer is a message of its author, the studio comment of `returned` — a message of the
  studio, `resolved` — the thread resolved. The same rules fill the threads from the answers
  already there (backfill, migration 0022).
- The studio accepts a message (accept: open → checking); the check (step 2) resolves the thread
  (resolve), gives it back (reopen, with a system message why) or starts a follow-up (follow_up:
  the thread superseded, its question leaves intake.yaml, a new question and thread follow with
  previous_thread_id). The studio closes a thread by hand (close).

Functions take an open Session and do not commit, as repositories.py.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import questions_yaml as qy
from floorplan_engine.service.db.models import (
    AnswerRevision,
    AppUser,
    Project,
    Question,
    QuestionRevision,
    QuestionThread,
    ThreadMessage,
    now,
)

STATES = ("open", "checking", "resolved", "superseded", "closed")
LIVE = ("open", "checking")  # at most one such thread per question
AUTHORS = ("user", "analyzer", "system")
# Who wrote an answer revision (questions.Author.kind) → who wrote its message
MESSAGE_AUTHOR = {"analyzer": "analyzer", "code": "system"}
CODE_LABEL = "код:"  # an answer by a client code: its label is «код: Иван»
QID = re.compile(r"q(\d+)")


class ThreadError(ValueError):
    """The action does not fit the thread: the message is for the user, in Russian."""


@dataclass(frozen=True)
class Writer:
    """Who writes a message: a user (user_id, or a client code by label), the analyzer or the
    system; role — their project role now ("" — not known)."""

    kind: str = "user"  # user | analyzer | system
    user_id: uuid.UUID | None = None
    label: str = ""
    role: str = ""


SYSTEM = Writer("system")
ANALYZER = Writer("analyzer")


# --- Reading ------------------------------------------------------------------------------


def live_thread(session: Session, question_id: uuid.UUID) -> QuestionThread | None:
    """The open or checking thread of a question, None if there is none."""
    return session.scalar(
        select(QuestionThread).where(
            QuestionThread.question_id == question_id, QuestionThread.state.in_(LIVE)
        )
    )


def latest_thread(session: Session, question_id: uuid.UUID) -> QuestionThread | None:
    """The newest thread of a question, in any state."""
    return session.scalar(
        select(QuestionThread)
        .where(QuestionThread.question_id == question_id)
        .order_by(QuestionThread.created_at.desc(), QuestionThread.id.desc())
        .limit(1)
    )


def messages(session: Session, thread: QuestionThread) -> list[ThreadMessage]:
    """The messages of a thread, oldest first."""
    return list(
        session.scalars(
            select(ThreadMessage)
            .where(ThreadMessage.thread_id == thread.id)
            .order_by(ThreadMessage.created_at, ThreadMessage.id)
        )
    )


def chain(session: Session, thread: QuestionThread) -> list[QuestionThread]:
    """The thread and the unresolved ones before it, newest first (its length is «3-й тред»)."""
    out = [thread]
    seen = {thread.id}
    while out[-1].previous_thread_id is not None and out[-1].previous_thread_id not in seen:
        previous = session.get(QuestionThread, out[-1].previous_thread_id)
        if previous is None:
            break
        seen.add(previous.id)
        out.append(previous)
    return out


# --- Writing ------------------------------------------------------------------------------


def open_thread(
    session: Session,
    question: Question,
    previous: QuestionThread | None = None,
    at: datetime | None = None,
) -> QuestionThread:
    """A new open thread of a question; a question has one open or checking thread at most."""
    if live_thread(session, question.id) is not None:
        raise ThreadError(f"у вопроса {question.qid} уже есть открытый тред")
    thread = QuestionThread(
        project_id=question.project_id,
        question_id=question.id,
        previous_thread_id=previous.id if previous is not None else None,
        state="open",
        created_at=at or now(),
    )
    session.add(thread)
    session.flush()
    return thread


def add_message(
    session: Session,
    thread: QuestionThread,
    writer: Writer,
    text: str,
    meta: dict[str, Any] | None = None,
    at: datetime | None = None,
) -> ThreadMessage:
    """A message in a thread. A message to a thread that is over (resolved, superseded, closed)
    is kept too: the discussion may go on after the answer."""
    if writer.kind not in AUTHORS:
        raise ThreadError(f"автор сообщения: {' | '.join(AUTHORS)}, не «{writer.kind}»")
    message = ThreadMessage(
        thread_id=thread.id,
        author=writer.kind,
        user_id=writer.user_id,
        author_label=writer.label,
        role=writer.role,
        text=text,
        meta=meta or {},
        created_at=at or now(),
    )
    session.add(message)
    session.flush()
    return message


def _state(thread: QuestionThread, *allowed: str) -> None:
    if thread.state not in allowed:
        raise ThreadError(f"тред в состоянии {thread.state}, нужно {' или '.join(allowed)}")


def _finish(thread: QuestionThread, state: str, at: datetime | None = None) -> None:
    thread.state = state
    thread.closed_at = at or now()


def accept(session: Session, thread: QuestionThread, message: ThreadMessage) -> None:
    """The studio accepts a message as the answer: the thread waits for the check (checking).
    A studio question with a value, a choice or panel groups is answered by the form (decision
    2026-11-28, п. 5); a client or installer question of any kind only clarifies, so its answer
    always goes through the accept and the AI check."""
    _state(thread, "open")
    if message.thread_id != thread.id:
        raise ThreadError("принять можно только сообщение этого треда")
    question = session.get(Question, thread.question_id) if thread.question_id else None
    if question is not None and question.kind != "text" and question.audience == "studio":
        raise ThreadError(
            f"на вопрос {question.qid} отвечают формой ({question.kind}), а не сообщением"
        )
    thread.state = "checking"
    thread.accepted_message_id = message.id
    session.flush()


def resolve(
    session: Session,
    thread: QuestionThread,
    version_id: uuid.UUID | None = None,
    at: datetime | None = None,
) -> None:
    """The question is answered: by the check of the accepted message (version_id — the model
    version it made) or by a form answer (open → resolved)."""
    _state(thread, *LIVE)
    _finish(thread, "resolved", at)
    if version_id is not None:
        thread.result_version_id = version_id
    session.flush()


def reopen(session: Session, thread: QuestionThread, reason: str) -> ThreadMessage:
    """The check did not succeed (the AI is not there, the YAML did not pass the check): the
    thread is open again and says why; the studio may accept again."""
    _state(thread, "checking")
    thread.state = "open"
    thread.accepted_message_id = None
    return add_message(session, thread, SYSTEM, reason)


def close(
    session: Session, thread: QuestionThread, writer: Writer | None = None, comment: str = ""
) -> None:
    """The studio closes an open thread by hand (solved by editing the sources, no longer
    relevant); the comment, if any, is its last message."""
    _state(thread, "open")
    if comment and writer is not None:
        add_message(session, thread, writer, comment)
    _finish(thread, "closed")
    session.flush()


def _latest_wording(session: Session, question: Question) -> QuestionRevision | None:
    return session.scalar(
        select(QuestionRevision)
        .where(QuestionRevision.question_id == question.id)
        .order_by(QuestionRevision.number.desc())
        .limit(1)
    )


def next_qid(session: Session, project_id: uuid.UUID) -> str:
    """A qid the project does not have yet: q<n> after the largest q<number>."""
    qids = session.scalars(select(Question.qid).where(Question.project_id == project_id))
    numbers = [int(m.group(1)) for q in qids if (m := QID.fullmatch(q))]
    return f"q{max(numbers, default=0) + 1}"


@dataclass(frozen=True)
class FollowUp:
    """The new question when an accepted answer did not close the old one (check_answer's
    `followup`): its text and, if not the old ones, its audience, severity and stage."""

    text: str
    audience: str | None = None
    severity: str | None = None
    stage: str | None = None


def follow_up(
    session: Session,
    thread: QuestionThread,
    ask: FollowUp,
    version_id: uuid.UUID | None = None,
) -> QuestionThread:
    """The accepted answer did not close the question: the thread is superseded, its question
    gets a revision `superseded` and leaves intake.yaml, a new question (a new qid, source
    analyzer, a text answer, in the old one's place) is asked with a new thread whose first
    message quotes the accepted answer. Returns the new thread."""
    _state(thread, "checking")
    old = session.get(Question, thread.question_id) if thread.question_id is not None else None
    if old is None:
        raise ThreadError("у треда нет вопроса: продолжить его новым вопросом нельзя")
    wording = _latest_wording(session, old)
    stamp = now()
    fields: dict[str, Any] = {
        "qid": next_qid(session, old.project_id),
        "stage": ask.stage or old.stage,
        "target": None,
        "also": [],
        "unit": None,
        "audience": ask.audience or old.audience,
        "kind": "text",
        "options": [],
        "option_labels": {},
        "text": ask.text,
        "assumption": None,
        "severity": ask.severity or (wording.severity if wording else None) or "major",
        "note": "",
    }
    try:
        qy.from_fields(fields)  # the same rules as intake.yaml
    except ValidationError as exc:
        raise ThreadError(f"новый вопрос не проходит проверку: {exc.errors()[0]['msg']}") from exc
    if wording is not None:
        session.add(
            QuestionRevision(
                question_id=old.id,
                number=wording.number + 1,
                text=wording.text,
                assumption=wording.assumption,
                severity=wording.severity,
                note=wording.note,
                reason="superseded",
                author="analyzer",
                author_label="",
                model_version_id=version_id,
                created_at=stamp,
            )
        )
    position, old.position = old.position, None
    new = Question(
        project_id=old.project_id,
        source="analyzer",
        position=position,
        **{k: fields[k] for k in ("qid", *qy.DEFINITION)},
    )
    session.add(new)
    session.flush()
    session.add(
        QuestionRevision(
            question_id=new.id,
            number=1,
            text=fields["text"],
            assumption=None,
            severity=fields["severity"],
            note="",
            reason="new",
            author="analyzer",
            author_label="",
            model_version_id=version_id,
            created_at=stamp,
        )
    )
    accepted = thread.accepted_message_id
    quote = session.get(ThreadMessage, accepted) if accepted is not None else None
    _finish(thread, "superseded", stamp)
    session.flush()
    nxt = open_thread(session, new, previous=thread, at=stamp)
    if quote is not None:
        meta = {"quote": str(quote.id), "previous_thread_id": str(thread.id)}
        add_message(session, nxt, SYSTEM, quote.text, meta, at=stamp)
    return nxt


# --- Answers into threads (questions.ingest, record_code, backfill) -----------------------


def role_of(session: Session, project: Project, user_id: uuid.UUID | None, label: str) -> str:
    """The project role of the author of an answer now: by their user, or client_code for an
    answer by a client code; "" — not known (a name from the log, a user gone)."""
    if user_id is None:
        return "client_code" if label.startswith(CODE_LABEL) else ""
    user = session.get(AppUser, user_id)
    if user is None:
        return ""
    return acc.project_role(session, acc.Principal(user), project) or ""


def _writer(session: Session, project: Project, revision: AnswerRevision) -> Writer:
    kind = MESSAGE_AUTHOR.get(revision.author, "user")
    role = role_of(session, project, revision.user_id, revision.author_label)
    return Writer(kind, revision.user_id, revision.author_label, role if kind == "user" else "")


def _text(value: Any, key: str) -> str | None:
    if isinstance(value, dict) and "text" in value and value.get(key):
        return str(value[key])
    return None


def _apply(
    session: Session,
    project: Project,
    thread: QuestionThread,
    previous: AnswerRevision | None,
    revision: AnswerRevision,
) -> None:
    """One answer revision into the question's thread: see the module docstring."""
    value, before = revision.value, previous.value if previous is not None else None
    at = revision.created_at
    if value is None:
        if thread.state == "resolved" and thread.accepted_message_id is None:
            thread.state, thread.closed_at = "open", None  # the form answer was removed
        return
    if not (isinstance(value, dict) and "text" in value):
        if thread.state == "open":
            resolve(session, thread, at=at)
        return
    writer = _writer(session, project, revision)
    accepted = (
        session.get(ThreadMessage, thread.accepted_message_id)
        if thread.accepted_message_id is not None
        else None
    )
    text = _text(value, "text")
    # The accepted message written into answers.yaml by the check is already in the thread
    if text != _text(before, "text") and (accepted is None or accepted.text != text):
        add_message(session, thread, writer, str(value["text"]), at=at)
    comment = _text(value, "returned")
    if comment is not None and comment != _text(before, "returned"):
        # After the answer it comments, also when both came in one revision
        add_message(session, thread, writer, comment, at=at + timedelta(microseconds=1))
    # A thread under the check is resolved by the check itself (answer_check), with its version
    if value.get("resolved") and thread.state == "open":
        resolve(session, thread, at=at)


@dataclass(frozen=True)
class Seen:
    """What a project had before a model version was read: its questions and answer revisions."""

    questions: frozenset[uuid.UUID]
    answers: frozenset[uuid.UUID]


def seen(session: Session, project_id: uuid.UUID) -> Seen:
    ids = select(Question.id).where(Question.project_id == project_id)
    answers = select(AnswerRevision.id).where(AnswerRevision.question_id.in_(ids))
    return Seen(frozenset(session.scalars(ids)), frozenset(session.scalars(answers)))


def _previous_answers(
    session: Session, revisions: list[AnswerRevision]
) -> dict[uuid.UUID, AnswerRevision]:
    """The answer revision just before each of these (by question and number)."""
    out: dict[uuid.UUID, AnswerRevision] = {}
    for r in revisions:
        previous = session.scalar(
            select(AnswerRevision).where(
                AnswerRevision.question_id == r.question_id,
                AnswerRevision.number == r.number - 1,
            )
        )
        if previous is not None:
            out[r.id] = previous
    return out


def follow(session: Session, project_id: uuid.UUID, before: Seen) -> None:
    """After a model version or a build was read into the question tables: a thread for each new
    question, the new answer revisions into their threads (_apply)."""
    project = session.get(Project, project_id)
    if project is None:
        return
    rows = session.scalars(
        select(Question).where(Question.project_id == project_id).order_by(Question.created_at)
    ).all()
    by_id = {q.id: q for q in rows}
    for q in rows:
        if q.id not in before.questions and latest_thread(session, q.id) is None:
            open_thread(session, q)
    revisions = [
        r
        for r in session.scalars(
            select(AnswerRevision)
            .where(AnswerRevision.question_id.in_(list(by_id)))
            .order_by(AnswerRevision.question_id, AnswerRevision.number)
        )
        if r.id not in before.answers
    ]
    previous = _previous_answers(session, revisions)
    for r in revisions:
        thread = live_thread(session, r.question_id) or latest_thread(session, r.question_id)
        if thread is None:
            thread = open_thread(session, by_id[r.question_id])
        _apply(session, project, thread, previous.get(r.id), r)
    session.flush()


def backfill(session: Session) -> int:
    """Threads for the questions that have none (migration 0022), from their answers in order:
    a text answer — a message of its author, `returned` — a message of the studio, `resolved` —
    the thread resolved (no check by the AI after the fact); a form answer — a resolved thread
    without messages; no answer — an open thread. Returns the number of threads made."""
    has = select(QuestionThread.question_id).where(QuestionThread.question_id.is_not(None))
    rows = session.scalars(
        select(Question).where(Question.id.not_in(has)).order_by(Question.project_id, Question.qid)
    ).all()
    projects: dict[uuid.UUID, Project | None] = {}
    for q in rows:
        project = projects.get(q.project_id) or session.get(Project, q.project_id)
        projects[q.project_id] = project
        answers = list(
            session.scalars(
                select(AnswerRevision)
                .where(AnswerRevision.question_id == q.id)
                .order_by(AnswerRevision.number)
            )
        )
        first = session.scalar(
            select(func.min(QuestionRevision.created_at)).where(
                QuestionRevision.question_id == q.id
            )
        )
        times = [t for t in (first, answers[0].created_at if answers else None) if t is not None]
        thread = open_thread(session, q, at=min(times) if times else q.created_at)
        if project is None:
            continue
        previous: AnswerRevision | None = None
        for r in answers:
            _apply(session, project, thread, previous, r)
            previous = r
    session.flush()
    return len(rows)
