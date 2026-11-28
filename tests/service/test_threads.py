"""Question threads (service/db/threads.py, docs/question-threads.md): every question gets an open
thread, the answers of model versions follow into it, the studio accepts a message, closes a
thread or a follow-up question replaces an unanswered one; the migration fills the threads from
the answers already there, and the YAML made from the tables stays byte for byte the same."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from floorplan_engine.model.intake import ANSWERS_FILE, INTAKE_FILE
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import questions, threads
from floorplan_engine.service.db import questions_yaml as qy
from floorplan_engine.service.db import repositories as repo
from floorplan_engine.service.db.models import (
    AppUser,
    Project,
    QuestionThread,
    ThreadMessage,
)
from floorplan_engine.validation.answers_file import build_digest
from tests.electrical.test_variants import _project
from tests.service import conftest

INTAKE = """\
sources:
  - { file: source/plan.pdf }
questions:
  # толщина не подписана
  - { id: q1, stage: plan, target: rooms.r.walls.w2.thickness, text: "Толщина w2?", answer: value }
  - { id: q2, stage: plan, audience: client, text: "Есть обмер?", answer: text, severity: major }
  - { id: q3, stage: electrical, audience: installer, text: "Где щит?", severity: minor }
"""
CODE = "код: Иван"


def _base(tmp_path: Path) -> dict[str, str]:
    folder = _project(tmp_path)
    return {p.name: p.read_text("utf-8") for p in folder.glob("*.yaml")}


def _owner(db: Session) -> tuple[Project, AppUser]:
    user = acc.oauth_login(db, "google", "o", "o@example.com", True, "Анна")
    studio = acc.register_firm(db, user, "Искра", "electric")
    return repo.create_project(db, studio.id, "Кв"), user


def _version(
    db: Session,
    project: Project,
    base: dict[str, str],
    answers: str | None,
    author: str = "user",
    user_id: uuid.UUID | None = None,
    label: str = "",
) -> None:
    files = {**base, INTAKE_FILE: INTAKE}
    if answers is not None:
        files[ANSWERS_FILE] = answers
    repo.add_model_version(db, project.id, files, author, user_id, label)


def _thread(db: Session, project: Project, qid: str) -> QuestionThread:
    row = questions.current(db, project.id)[qid].row
    thread = threads.latest_thread(db, row.id)
    assert thread is not None
    return thread


def _said(db: Session, thread: QuestionThread) -> list[tuple[str, str, str, str]]:
    return [(m.author, m.author_label, m.role, m.text) for m in threads.messages(db, thread)]


def _history(db: Session, project: Project, base: dict[str, str], owner: AppUser) -> None:
    """Questions, a form answer, a client text answer returned, answered again and resolved."""
    _version(db, project, base, None, "analyzer")
    _version(db, project, base, "answers:\n  q1: 150 # по обмеру\n", "operator")
    q2 = 'answers:\n  q1: 150 # по обмеру\n  q2: { text: "обмера нет" }\n'
    _version(db, project, base, q2, label=CODE)
    returned = q2.replace('" }', '", returned: "Пришлите фото" }')
    _version(db, project, base, returned, user_id=owner.id)
    again = 'answers:\n  q1: 150 # по обмеру\n  q2: { text: "фото в source" }\n'
    _version(db, project, base, again, label=CODE)
    _version(db, project, base, again.replace('" }', '", resolved: true }'), user_id=owner.id)


def _states(db: Session, project: Project) -> dict[str, tuple[str, list[Any]]]:
    out = {}
    for qid in ("q1", "q2", "q3"):
        thread = _thread(db, project, qid)
        out[qid] = (thread.state, _said(db, thread))
    return out


EXPECTED = {
    "q1": ("resolved", []),
    "q2": (
        "resolved",
        [
            ("user", CODE, "client_code", "обмера нет"),
            ("user", "", "owner", "Пришлите фото"),
            ("user", CODE, "client_code", "фото в source"),
        ],
    ),
    "q3": ("open", []),
}


def test_answers_follow_into_threads(db: Session, tmp_path: Path) -> None:
    project, owner = _owner(db)
    base = _base(tmp_path)
    _version(db, project, base, None, "analyzer")
    assert {qid: s for qid, (s, _) in _states(db, project).items()} == dict.fromkeys(
        ("q1", "q2", "q3"), "open"
    )
    _history(db, project, base, owner)
    assert _states(db, project) == EXPECTED
    q1 = _thread(db, project, "q1")
    assert q1.closed_at is not None and q1.accepted_message_id is None
    # One thread per question: the answers went into the same one
    count = db.scalars(select(QuestionThread).where(QuestionThread.project_id == project.id))
    assert len(count.all()) == 3

    # The form answer removed: the question is open again, in the same thread
    _version(db, project, base, 'answers:\n  q2: { text: "фото в source", resolved: true }\n')
    q1 = _thread(db, project, "q1")
    assert (q1.state, q1.closed_at) == ("open", None)


def test_code_questions_get_threads(db: Session, tmp_path: Path) -> None:
    project, _ = _owner(db)
    version = repo.add_model_version(db, project.id, _base(tmp_path), "user")
    report = {"questions": [{"id": "panel_input", "stage": "panel", "text": "Ввод?"}]}
    questions.record_code(db, project.id, version.id, report)
    assert _thread(db, project, "panel_input").state == "open"
    questions.record_code(db, project.id, version.id, report)  # the same: no second thread
    answers = {ANSWERS_FILE: "answers:\n  panel_input: 40\n"}
    repo.add_model_version(db, project.id, answers, "user")
    thread = _thread(db, project, "panel_input")
    assert thread.state == "resolved"
    assert len(db.scalars(select(QuestionThread)).all()) == 1


def test_accept_close_and_the_check_states(db: Session, tmp_path: Path) -> None:
    project, owner = _owner(db)
    _version(db, project, _base(tmp_path), None, "analyzer")
    thread = _thread(db, project, "q2")
    other = _thread(db, project, "q3")
    client = threads.Writer("user", None, CODE, "client_code")
    message = threads.add_message(db, thread, client, "обмера нет")
    with pytest.raises(threads.ThreadError, match="только сообщение этого треда"):
        threads.accept(db, other, message)
    threads.accept(db, thread, message)
    assert (thread.state, thread.accepted_message_id) == ("checking", message.id)
    with pytest.raises(threads.ThreadError, match="нужно open"):
        threads.close(db, thread)
    # The check did not succeed: open again, with the reason
    threads.reopen(db, thread, "ИИ недоступен")
    assert (thread.state, thread.accepted_message_id) == ("open", None)
    assert _said(db, thread)[-1] == ("system", "", "", "ИИ недоступен")
    threads.accept(db, thread, message)
    version = repo.latest_model(db, project.id)
    assert version is not None
    threads.resolve(db, thread, version.id)
    assert (thread.state, thread.result_version_id) == ("resolved", version.id)
    assert thread.closed_at is not None
    with pytest.raises(threads.ThreadError):
        threads.accept(db, thread, message)

    studio = threads.Writer("user", owner.id, "Анна", "owner")
    threads.close(db, other, studio, "решено правкой исходников")
    assert other.state == "closed" and other.closed_at is not None
    assert _said(db, other) == [("user", "Анна", "owner", "решено правкой исходников")]
    with pytest.raises(threads.ThreadError, match="автор сообщения"):
        threads.add_message(db, other, threads.Writer("robot"), "?")


def test_one_live_thread_per_question(db: Session, tmp_path: Path) -> None:
    project, _ = _owner(db)
    _version(db, project, _base(tmp_path), None, "analyzer")
    row = questions.current(db, project.id)["q3"].row
    with pytest.raises(threads.ThreadError, match="уже есть открытый тред"):
        threads.open_thread(db, row)
    db.add(QuestionThread(project_id=project.id, question_id=row.id, state="checking"))
    with pytest.raises(IntegrityError):
        db.flush()  # the partial unique index holds even past the code
    db.rollback()


def test_follow_up_replaces_an_unanswered_question(db: Session, tmp_path: Path) -> None:
    project, _ = _owner(db)
    base = _base(tmp_path)
    _version(db, project, base, None, "analyzer")
    thread = _thread(db, project, "q3")
    installer = threads.Writer("user", None, "Петро", "installer")
    answer = threads.add_message(db, thread, installer, "как на кухне")
    with pytest.raises(threads.ThreadError, match="нужно checking"):
        threads.follow_up(db, thread, threads.FollowUp("Где щит, на какой стене?"))
    threads.accept(db, thread, answer)
    with pytest.raises(threads.ThreadError, match="не проходит проверку"):
        threads.follow_up(db, thread, threads.FollowUp("Где?", severity="huge"))
    nxt = threads.follow_up(db, thread, threads.FollowUp("Где щит, на какой стене?"))
    assert thread.state == "superseded" and thread.closed_at is not None
    assert nxt.state == "open" and nxt.previous_thread_id == thread.id
    assert threads.chain(db, nxt) == [nxt, thread]
    quote = threads.messages(db, nxt)
    assert [(m.author, m.text, m.meta["quote"]) for m in quote] == [
        ("system", "как на кухне", str(answer.id))
    ]
    cur = questions.current(db, project.id)
    q3, q4 = cur["q3"], cur["q4"]
    assert q3.wording is not None and q3.wording.reason == "superseded"
    assert (q3.row.position, q4.row.position) == (None, 2)  # in the old one's place
    assert (q4.row.source, q4.row.audience, q4.row.kind) == ("analyzer", "installer", "text")
    assert q4.wording is not None and q4.wording.severity == "minor"

    # intake.yaml from the tables asks the new question instead of the old one
    latest = repo.latest_model(db, project.id)
    assert latest is not None
    intake = questions.texts(db, project.id, latest)[INTAKE_FILE]
    assert intake is not None
    asked = qy.intake_questions(intake)
    assert asked is not None and [f["qid"] for f in asked] == ["q1", "q2", "q4"]
    # A version made of that text: no new threads, q3 is not asked again
    repo.add_model_version(db, project.id, {**base, INTAKE_FILE: intake}, "user")
    assert len(db.scalars(select(QuestionThread)).all()) == 4
    assert threads.live_thread(db, q4.row.id) == nxt


def _texts(db: Session, project_id: uuid.UUID) -> dict[str, str | None]:
    latest = repo.latest_model(db, project_id)
    assert latest is not None
    return questions.texts(db, project_id, latest)


def test_backfill_gives_the_same_threads(db: Session, tmp_path: Path) -> None:
    project, owner = _owner(db)
    _history(db, project, _base(tmp_path), owner)
    before = _texts(db, project.id)
    db.execute(delete(ThreadMessage))
    db.execute(delete(QuestionThread))
    assert threads.backfill(db) == 3
    assert _states(db, project) == EXPECTED
    assert threads.backfill(db) == 0  # questions with threads are skipped
    assert _texts(db, project.id) == before


def test_migration_fills_threads_and_keeps_the_yaml(pg: Engine, tmp_path: Path) -> None:
    """Migration 0022 on a database with answers from before it: the threads are made, and
    intake.yaml and answers.yaml from the tables are byte for byte the same (the same
    answers_digest)."""
    base = _base(tmp_path)
    with Session(pg) as db:
        project, owner = _owner(db)
        _history(db, project, base, owner)
        pid = project.id
        db.commit()
    conftest.migrate(pg, "0021", down=True)
    try:
        with Session(pg) as db:
            before = _texts(db, pid)
    finally:
        conftest.migrate(pg, "head")
    with Session(pg) as db:
        row = db.get(Project, pid)
        assert row is not None
        assert _states(db, row) == EXPECTED
        after = _texts(db, pid)
        assert after == before
        assert build_digest(after[ANSWERS_FILE]) == build_digest(before[ANSWERS_FILE])


def test_only_text_answers_are_accepted_and_the_check_resolves(db: Session, tmp_path: Path) -> None:
    """A value question is answered by the form; a text answer written by the check (the accepted
    message, resolved) is not repeated in the thread and does not resolve it past the check."""
    project, _ = _owner(db)
    base = _base(tmp_path)
    _version(db, project, base, None, "analyzer")
    q1 = _thread(db, project, "q1")
    message = threads.add_message(db, q1, threads.Writer(), "150")
    with pytest.raises(threads.ThreadError, match="отвечают формой"):
        threads.accept(db, q1, message)
    q2 = _thread(db, project, "q2")
    answer = threads.add_message(db, q2, threads.Writer("user", None, CODE), "обмера нет")
    threads.accept(db, q2, answer)
    _version(
        db, project, base, 'answers:\n  q2: { text: "обмера нет", resolved: true }\n', "analyzer"
    )
    assert q2.state == "checking"
    assert [m.text for m in threads.messages(db, q2)] == ["обмера нет"]
