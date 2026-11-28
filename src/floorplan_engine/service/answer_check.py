"""The check of an accepted answer (docs/question-threads.md, «Проверка ответа ИИ»; the rules for
the model — analyzer_prompt.md, «Проверка ответа»). The studio accepts a message of a question
thread (threads.accept, then AnswerChecks.check_thread): the thread is `checking` and the project
goes into the queue. The check:

1. The latest model version is laid out in a temporary folder (project_store.workdir: intake.yaml
   and answers.yaml from the tables), the input is gathered — the question, the thread, the
   earlier threads of the chain, the stage's files and the errors of their check
   (check_answer.CheckInput) — and the model is asked (check_answer, the analyzer's backends).
   The transaction is closed while the model thinks.
2. `satisfied`: its files and the answer `{ text: <accepted>, resolved: true }` are written into
   the folder and the core checks them (validate_project). No new errors — a new model version by
   the analyzer, the thread resolved with it, an `analyzer` message with the reason and the
   changes, a rebuild. New errors — one retry with them in the same conversation; then the thread
   is open again with a system message.
3. `unsatisfied`: an `analyzer` message with the reason, the thread superseded, a new question
   and thread from `followup` (threads.follow_up), a rebuild (the report shows the new question).
4. The model is not there or answers nonsense — the thread is open again, the reason in a system
   message. The model changed during the check (someone answered) — the check is run again on the
   new model, at most STALE_RUNS times.

One check per project at a time, across servers: a Postgres advisory lock of the project held for
the run (AnswerChecks); the work is taken from the database, the project's checking threads one by
one, oldest first; other projects run in parallel (tasks.TaskQueue). A thread left `checking` by a
stop or a dead server is found again by recover and the sweep. Every model call is written into
`usage`.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import ColumnElement, Engine, func, literal, select
from sqlalchemy.orm import Session, sessionmaker

from floorplan_engine.model.intake import ANSWERS_FILE, AnswerNote, TextAnswer
from floorplan_engine.service import project_store as ps
from floorplan_engine.service import sync
from floorplan_engine.service.analysis import check_answer as ca
from floorplan_engine.service.analysis.llm_analyzer import Backend, Reply
from floorplan_engine.service.db import questions, threads
from floorplan_engine.service.db import repositories as repo
from floorplan_engine.service.db.models import (
    Project,
    Question,
    QuestionThread,
    ThreadMessage,
)
from floorplan_engine.service.objects import ObjectStore
from floorplan_engine.service.tasks import WORKERS, TaskQueue
from floorplan_engine.validation.answers_file import edit_answers
from floorplan_engine.validation.validate import validate_project

RETRIES = 1  # a patch with new errors is sent back once
STALE_RUNS = 2  # the model changed under the check: run it again this many times
SWEEP_SECONDS = 60.0  # how often to look for threads left `checking` by a dead holder
# The class id of the checks' advisory locks (the two-int form): no other lock uses it
LOCK_CLASS = 20261128
ANALYZER_LABEL = "ИИ"
log = logging.getLogger(__name__)

Rebuild = Callable[[Session, Project], object]


@dataclass
class _Outcome:
    """What a check came to: a verdict that passed the core, or why the thread is open again."""

    verdict: ca.Verdict | None = None
    files: dict[str, str] = field(default_factory=dict)  # the model folder after the patch
    failure: str = ""


def next_checking(session: Session, project_id: uuid.UUID) -> QuestionThread | None:
    """The project's oldest thread waiting for the check."""
    return session.scalar(
        select(QuestionThread)
        .where(QuestionThread.project_id == project_id, QuestionThread.state == "checking")
        .order_by(QuestionThread.created_at, QuestionThread.id)
        .limit(1)
    )


def gather(
    session: Session, thread: QuestionThread, question: Question, folder: Path
) -> ca.CheckInput:
    """The input of the check from the tables and the model folder."""
    cur = questions.current(session, thread.project_id)[question.qid]
    wording = cur.wording
    said = [
        ca.Said(m.author, m.role, m.author_label, m.text, m.id == thread.accepted_message_id)
        for m in threads.messages(session, thread)
    ]
    accepted = session.get(ThreadMessage, thread.accepted_message_id)
    earlier = []
    for t in threads.chain(session, thread)[1:]:
        q = session.get(Question, t.question_id) if t.question_id else None
        a = session.get(ThreadMessage, t.accepted_message_id) if t.accepted_message_id else None
        if q is not None and a is not None:
            text = questions.current(session, t.project_id)[q.qid].wording
            earlier.append(ca.Earlier(text.text if text else q.qid, a.text))
    names = ca.stage_files(question.stage)
    return ca.CheckInput(
        qid=question.qid,
        stage=question.stage,
        audience=question.audience,
        text=wording.text if wording is not None else "",
        target=question.target,
        assumption=wording.assumption if wording is not None else None,
        messages=said,
        accepted=accepted.text if accepted is not None else "",
        earlier=earlier,
        files={n: (folder / n).read_text("utf-8") for n in names if (folder / n).is_file()},
        errors=[str(e) for e in validate_project(folder).errors],
    )


def _patch(folder: Path, inp: ca.CheckInput, verdict: ca.Verdict) -> list[str]:
    """Write the verdict's files and the resolved answer into the folder; the problems the core
    finds that the model had not (empty — the patch is good)."""
    wrong = [n for n in verdict.files if n not in inp.writable]
    if wrong:
        return [f"{', '.join(wrong)}: в этом вопросе меняются только {', '.join(inp.writable)}"]
    for name, text in verdict.files.items():
        (folder / name).write_text(text, "utf-8")
    path = folder / ANSWERS_FILE
    note = AnswerNote(at=datetime.now(UTC).isoformat(timespec="seconds"), by=ANALYZER_LABEL)
    answer = TextAnswer(text=inp.accepted, resolved=True)
    text = path.read_text("utf-8") if path.is_file() else ""
    path.write_text(edit_answers(text, inp.qid, answer, note), "utf-8")
    before = set(inp.errors)
    return [str(e) for e in validate_project(folder).errors if str(e) not in before]


def _restore(folder: Path, original: dict[str, str | None]) -> None:
    for name, text in original.items():
        path = folder / name
        if text is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(text, "utf-8")


def _lock_key(project_id: uuid.UUID) -> tuple[ColumnElement[int], ColumnElement[int]]:
    """The advisory lock of a project's checks: the two-int form (LOCK_CLASS, hashtext(id)). Its
    key space does not overlap the one-bigint form of project_store.lock (the build lock), so the
    two never collide."""
    return literal(LOCK_CLASS), func.hashtext(str(project_id))


def pending(session: Session, project_id: uuid.UUID) -> bool:
    """The project has a thread waiting for the check."""
    return next_checking(session, project_id) is not None


class AnswerChecks:
    """The queue of answer checks. make_backend gives a new model conversation per check
    (check_answer.make_check_backend; a fake one in tests); rebuild builds the project's latest
    version (project_store.build by default); workers=0 runs a check inside submit.

    One check per project at a time across all servers: the run holds a session advisory lock of
    the project (pg_try_advisory_lock on a connection of its own, kept while the model thinks —
    the transactions are committed meanwhile) and takes the work from the database, the
    project's `checking` threads oldest first, until none is left. A server that does not get the
    lock returns at once: the holder sees the thread on its next scan, and after releasing it
    looks once more, so a thread accepted between its last scan and the release is not lost. A
    holder that dies releases the lock with its connection; the sweep (every SWEEP_SECONDS, and
    recover on start) queues the projects whose threads are still `checking`."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        store: ObjectStore,
        make_backend: Callable[[], Backend],
        workers: int = WORKERS,
        rebuild: Rebuild | None = None,
    ) -> None:
        self.sessions = sessions
        self.engine: Engine = sessions.kw["bind"]
        self.store = store
        self.make_backend = make_backend
        self.rebuild: Rebuild = rebuild or (lambda db, p: ps.build(db, store, p))
        self._queue = TaskQueue(self._task, workers)
        self._stale: dict[uuid.UUID, int] = {}
        self._stopping = threading.Event()
        self._sweeper: threading.Thread | None = None

    # --- What step 3 (the API) calls ---------------------------------------------------

    def check_thread(self, project_id: uuid.UUID, thread_id: uuid.UUID) -> None:
        """The hook after `accept` (threads.accept, committed): queue the project's check. The
        thread is not checked here by its id: the run takes the project's checking threads
        oldest first, so a thread accepted twice in a row is checked once."""
        log.info("проверка ответа: тред %s проекта %s в очереди", thread_id, project_id)
        self.submit(project_id)

    def submit(self, project_id: uuid.UUID) -> None:
        self._queue.submit(str(project_id))

    def recover(self) -> list[uuid.UUID]:
        """Queue every project with a thread left `checking` (on start and by the sweep): a
        project another server is checking is skipped there by its lock."""
        with self.sessions() as db:
            ids = list(
                db.scalars(
                    select(QuestionThread.project_id)
                    .where(QuestionThread.state == "checking")
                    .distinct()
                )
            )
        for pid in ids:
            self.submit(pid)
        return ids

    def start(self, sweep_seconds: float | None = SWEEP_SECONDS) -> None:
        """Start the workers, queue what was left `checking`, and sweep for it every
        sweep_seconds (None — no sweep)."""
        self._queue.start()
        self._stopping.clear()
        self.recover()
        if sweep_seconds is not None and self._sweeper is None:
            self._sweeper = threading.Thread(
                target=self._sweep, args=(sweep_seconds,), name="answer-sweep", daemon=True
            )
            self._sweeper.start()

    def _sweep(self, seconds: float) -> None:
        while not self._stopping.wait(seconds):
            try:
                self.recover()
            except Exception:
                log.exception("проверка ответа: обход тредов checking")

    def stop(self) -> None:
        self._stopping.set()
        sweeper, self._sweeper = self._sweeper, None
        if sweeper is not None:
            sweeper.join(5.0)
        self._queue.stop()

    def join(self) -> None:
        self._queue.join()

    # --- The run ----------------------------------------------------------------------

    def _task(self, key: str) -> None:
        self.run_project(uuid.UUID(key))

    def run_project(self, project_id: uuid.UUID) -> bool:
        """Check the project's waiting threads under its lock; False if another run holds it."""
        ran = False
        while True:
            if not self._drain(project_id):
                return ran
            ran = True
            with self.sessions() as db:
                if not pending(db, project_id):
                    return ran
            # A thread came between the last scan and the release: take the lock again

    def _drain(self, project_id: uuid.UUID) -> bool:
        """Under the project's lock, check its waiting threads until none is left; False if the
        lock is held elsewhere."""
        cls, obj = _lock_key(project_id)
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            if not conn.scalar(select(func.pg_try_advisory_lock(cls, obj))):
                return False
            try:
                while self._check_next(project_id):
                    pass
            finally:
                conn.scalar(select(func.pg_advisory_unlock(cls, obj)))
        return True

    def _check_next(self, project_id: uuid.UUID) -> bool:
        """One waiting thread of the project; False if there is none."""
        with self.sessions() as db:
            thread = next_checking(db, project_id)
            if thread is None:
                return False
            try:
                self._check(db, thread)
            except Exception as exc:
                log.exception("проверка ответа, тред %s", thread.id)
                db.rollback()
                thread = db.get(QuestionThread, thread.id)
                if thread is not None and thread.state == "checking":
                    threads.reopen(db, thread, f"Проверка ответа не удалась: {exc}")
            db.commit()
        return True

    def _check(self, db: Session, thread: QuestionThread) -> None:
        project = db.get(Project, thread.project_id)
        question = db.get(Question, thread.question_id) if thread.question_id else None
        base = repo.latest_model(db, thread.project_id)
        if project is None or question is None or base is None:
            threads.reopen(db, thread, "Проверка ответа: у треда нет вопроса или модели")
            return
        with ps.workdir(db, self.store, project) as folder:
            inp = gather(db, thread, question, folder)
            db.commit()  # no transaction held while the model thinks
            outcome = self._ask(db, project, folder, inp)
        db.expire_all()  # the sessions keep objects on commit: read what others wrote meanwhile
        thread = db.get(QuestionThread, thread.id) or thread
        if thread.state != "checking":
            return  # closed or answered by hand meanwhile: the result is not needed
        ps.lock(db, project)
        latest = repo.latest_model(db, project.id)
        if outcome.failure:
            threads.reopen(db, thread, outcome.failure)
            return
        if latest is None or latest.id != base.id:
            self._again_or_reopen(db, thread)
            return
        self._stale.pop(thread.id, None)
        verdict = outcome.verdict
        assert verdict is not None
        meta: dict[str, Any] = {"verdict": "satisfied" if verdict.satisfied else "unsatisfied"}
        if verdict.satisfied:
            meta["changes"] = verdict.changes
        text = verdict.reason + "".join(f"\n— {c}" for c in verdict.changes)
        threads.add_message(db, thread, threads.ANALYZER, text.strip(), meta)
        if verdict.satisfied:
            version = repo.add_model_version(db, project.id, outcome.files, "analyzer")
            threads.resolve(db, thread, version.id)
        else:
            ask = verdict.followup
            assert ask is not None
            threads.follow_up(
                db,
                thread,
                threads.FollowUp(ask.text, ask.audience, ask.severity, ask.stage),
                version_id=base.id,
            )
        db.flush()
        self.rebuild(db, project)

    def _again_or_reopen(self, db: Session, thread: QuestionThread) -> None:
        runs = self._stale.get(thread.id, 0) + 1
        if runs > STALE_RUNS:
            self._stale.pop(thread.id, None)
            threads.reopen(
                db, thread, "Модель менялась во время проверки ответа — примите ответ снова"
            )
            return
        self._stale[thread.id] = runs  # still checking: the next pass runs it on the new model

    def _ask(self, db: Session, project: Project, folder: Path, inp: ca.CheckInput) -> _Outcome:
        """The model's verdict that passed the core (with the folder's model files), or the
        failure. Usage of every call is committed at once."""
        backend = self.make_backend()
        original = {
            n: (folder / n).read_text("utf-8") if (folder / n).is_file() else None
            for n in (*ca.CHECK_FILES, ANSWERS_FILE)
        }
        try:
            reply = backend.start(folder, ca.check_prompt(inp))
            self._usage(db, project, backend, reply)
            for attempt in range(RETRIES + 1):
                verdict = ca.parse_verdict(reply.envelope)
                if not verdict.satisfied:
                    return _Outcome(verdict)
                problems = _patch(folder, inp, verdict)
                if not problems:
                    return _Outcome(verdict, sync.model_files(folder))
                _restore(folder, original)
                if attempt == RETRIES:
                    shown = "\n".join(f"- {p}" for p in problems[:10])
                    return _Outcome(
                        failure=f"Ответ не перенесён: модель не прошла проверку\n{shown}"
                    )
                reply = backend.follow_up(folder, ca.retry_prompt(problems))
                self._usage(db, project, backend, reply)
        except Exception as exc:
            log.warning("проверка ответа %s: %s", inp.qid, exc)
            return _Outcome(failure=f"Проверка ответа не удалась: {exc}")
        return _Outcome(failure="Проверка ответа не удалась")  # pragma: no cover

    @staticmethod
    def _usage(db: Session, project: Project, backend: Backend, reply: Reply) -> None:
        u = reply.usage.priced()
        repo.record_usage(
            db,
            project.id,
            project.round,
            backend.name,
            u.cost_usd or 0.0,
            u.model,
            u.input_tokens,
            u.output_tokens,
        )
        db.commit()
