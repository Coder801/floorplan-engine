"""The check of an accepted answer (service/answer_check.py) with a fake model: no tokens. A
satisfied verdict becomes a model version by the analyzer, the thread resolved and a rebuild; a
patch with new errors is retried once and then given back; an unsatisfied one continues the chain
with a new question; a broken model or envelope opens the thread again; one check per project at
a time, the threads accepted meanwhile are not lost."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from floorplan_engine.model.intake import ANSWERS_FILE, INTAKE_FILE
from floorplan_engine.service.analysis.llm_analyzer import AnalyzerError, Reply, Usage
from floorplan_engine.service.answer_check import LOCK_CLASS, AnswerChecks, next_checking
from floorplan_engine.service.db import questions, threads
from floorplan_engine.service.db import repositories as repo
from floorplan_engine.service.db.models import (
    ModelVersion,
    Project,
    QuestionThread,
    ThreadMessage,
)
from floorplan_engine.service.db.models import Usage as UsageRow
from floorplan_engine.service.objects import LocalObjectStore
from tests.electrical.test_variants import _project

INTAKE = """\
sources: []
questions:
  - { id: q1, stage: plan, audience: client, text: "Толщина стен?", severity: major }
  - { id: q2, stage: electrical, audience: installer, text: "Где ввод?", severity: minor }
  - { id: q3, stage: plan, target: rooms.r.walls.w2.length, text: "Длина w2?", answer: value }
"""


@dataclass
class Fake:
    """A model that answers from a script: an envelope, or an exception to raise."""

    script: list[Any]
    name: str = "fake"
    prompts: list[str] = field(default_factory=list)
    on_call: Any = None

    def _next(self, prompt: str) -> Reply:
        self.prompts.append(prompt)
        if self.on_call is not None:
            self.on_call()
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        usage = Usage("claude-opus-5-5", input_tokens=1000, output_tokens=100)
        return Reply(item, usage)

    def start(self, project: Path, prompt: str) -> Reply:
        return self._next(prompt)

    def follow_up(self, project: Path, prompt: str) -> Reply:
        return self._next(prompt)


def satisfied(room: str | None, changes: list[str] | None = None) -> dict[str, Any]:
    files = [] if room is None else [{"name": "room.yaml", "content": room}]
    return {
        "verdict": "satisfied",
        "reason": "ответ даёт толщину",
        "changes": changes or [],
        "files": files,
        "followup": None,
    }


UNSATISFIED = {
    "verdict": "unsatisfied",
    "reason": "размер не назван",
    "changes": [],
    "files": [],
    "followup": {"text": "Какая толщина стен, мм?", "audience": "installer"},
}


class World:
    def __init__(self, sessions: sessionmaker[Session], tmp_path: Path, slug: str = "kv") -> None:
        self.sessions = sessions
        self.store = LocalObjectStore(tmp_path / "store")
        tmp_path.mkdir(parents=True, exist_ok=True)
        folder = _project(tmp_path)
        self.room = (folder / "room.yaml").read_text("utf-8")
        files = {p.name: p.read_text("utf-8") for p in folder.glob("*.yaml")}
        with sessions() as db:
            project = repo.create_project(db, repo.create_studio(db, "Искра").id, "Кв")
            project.slug = slug
            repo.add_model_version(db, project.id, {**files, INTAKE_FILE: INTAKE}, "analyzer")
            db.commit()
            self.pid = project.id
        self.rebuilt: list[uuid.UUID] = []
        self.fake = Fake([])
        self.checks = AnswerChecks(
            sessions, self.store, lambda: self.fake, workers=0, rebuild=self._rebuild
        )

    def _rebuild(self, db: Session, project: Project) -> None:
        self.rebuilt.append(project.id)

    def accept(self, qid: str, text: str, role: str = "client_code") -> uuid.UUID:
        """A message in the question's thread, accepted by the studio (committed)."""
        with self.sessions() as db:
            row = questions.current(db, self.pid)[qid].row
            thread = threads.live_thread(db, row.id)
            assert thread is not None
            writer = threads.Writer("user", None, "код: Иван", role)
            message = threads.add_message(db, thread, writer, text)
            threads.accept(db, thread, message)
            db.commit()
            return thread.id

    def check(self, thread_id: uuid.UUID) -> None:
        self.checks.check_thread(self.pid, thread_id)

    def thread(self, db: Session, thread_id: uuid.UUID) -> QuestionThread:
        thread = db.get(QuestionThread, thread_id)
        assert thread is not None
        return thread

    def said(self, db: Session, thread_id: uuid.UUID) -> list[tuple[str, str]]:
        return [(m.author, m.text) for m in threads.messages(db, self.thread(db, thread_id))]

    def versions(self, db: Session) -> list[ModelVersion]:
        return list(
            db.scalars(
                select(ModelVersion)
                .where(ModelVersion.project_id == self.pid)
                .order_by(ModelVersion.version)
            )
        )


def test_satisfied_answer_becomes_a_version(
    sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    w = World(sessions, tmp_path)
    room = w.room.replace("default_wall_thickness: 120", "default_wall_thickness: 150")
    w.fake.script = [satisfied(room, ["room.yaml: default_wall_thickness 120 → 150"])]
    tid = w.accept("q1", "все стены 150 мм")
    w.check(tid)
    with sessions() as db:
        thread = w.thread(db, tid)
        versions = w.versions(db)
        assert len(versions) == 2 and versions[-1].author == "analyzer"
        assert (thread.state, thread.result_version_id) == ("resolved", versions[-1].id)
        assert versions[-1].room_yaml == room
        answers = yaml.safe_load(versions[-1].answers_yaml or "")
        assert answers["answers"]["q1"] == {"text": "все стены 150 мм", "resolved": True}
        assert answers["log"]["q1"]["by"] == "ИИ"
        # The accepted message is not repeated; the analyzer says why and what changed
        said = w.said(db, tid)
        assert said[0] == ("user", "все стены 150 мм") and len(said) == 2
        last = threads.messages(db, thread)[-1]
        assert last.author == "analyzer" and "120 → 150" in last.text
        assert last.meta == {
            "verdict": "satisfied",
            "changes": ["room.yaml: default_wall_thickness 120 → 150"],
        }
        usage = db.scalars(select(UsageRow).where(UsageRow.project_id == w.pid)).all()
        assert [(u.backend, u.input_tokens) for u in usage] == [("fake", 1000)]
        assert usage[0].cost_usd > 0  # priced by the model's price
    assert w.rebuilt == [w.pid]
    prompt = w.fake.prompts[0]
    assert prompt.startswith("Проверка ответа.") and "все стены 150 мм" in prompt
    assert "(принято студией)" in prompt and "--- room.yaml" in prompt
    assert "electrical.yaml" not in prompt  # the plan question sees the plan only


def test_answer_without_model_change(sessions: sessionmaker[Session], tmp_path: Path) -> None:
    w = World(sessions, tmp_path)
    w.fake.script = [satisfied(None)]
    tid = w.accept("q2", "ввод в коридоре, над дверью", "installer")
    w.check(tid)
    with sessions() as db:
        assert w.thread(db, tid).state == "resolved"
        assert w.versions(db)[-1].room_yaml == w.room


def test_invalid_patch_is_retried_then_given_back(
    sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    w = World(sessions, tmp_path)
    bad = w.room.replace("default_wall_thickness: 120", "default_wall_thickness: -5")
    w.fake.script = [satisfied(bad), satisfied(bad)]
    tid = w.accept("q1", "минус пять")
    w.check(tid)
    assert len(w.fake.prompts) == 2 and "новые ошибки" in w.fake.prompts[1]
    with sessions() as db:
        thread = w.thread(db, tid)
        assert (thread.state, thread.accepted_message_id) == ("open", None)
        author, text = w.said(db, tid)[-1]
        assert author == "system" and "не прошла проверку" in text
        assert "default_wall_thickness" in text  # the error with its field path
        assert len(w.versions(db)) == 1  # nothing written
    assert w.rebuilt == []

    # Accepted again: the retry fixes it
    good = w.room.replace("default_wall_thickness: 120", "default_wall_thickness: 150")
    w.fake.script = [satisfied(bad), satisfied(good)]
    with sessions() as db:
        message = threads.messages(db, w.thread(db, tid))[0]
        threads.accept(db, w.thread(db, tid), message)
        db.commit()
    w.check(tid)
    with sessions() as db:
        assert w.thread(db, tid).state == "resolved"
        assert w.versions(db)[-1].room_yaml == good


def test_unsatisfied_answer_continues_the_chain(
    sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    w = World(sessions, tmp_path)
    w.fake.script = [UNSATISFIED]
    tid = w.accept("q1", "как у соседей")
    w.check(tid)
    with sessions() as db:
        old = w.thread(db, tid)
        assert old.state == "superseded"
        assert w.said(db, tid)[-1] == ("analyzer", "размер не назван")
        cur = questions.current(db, w.pid)
        new = cur["q4"]
        assert (new.row.audience, new.row.position) == ("installer", 0)
        assert cur["q1"].row.position is None
        nxt = threads.live_thread(db, new.row.id)
        assert nxt is not None and nxt.previous_thread_id == tid
        assert [(m.author, m.text) for m in threads.messages(db, nxt)] == [
            ("system", "как у соседей")
        ]
        assert len(w.versions(db)) == 1
        message = threads.add_message(db, nxt, threads.Writer("user", None, "Петро"), "120 мм")
        threads.accept(db, nxt, message)
        db.commit()
        nid = nxt.id
    assert w.rebuilt == [w.pid]
    # The next check sees the earlier thread of the chain
    w.fake.script = [satisfied(None)]
    w.check(nid)
    assert "Предыдущие треды цепочки" in w.fake.prompts[-1]
    assert "как у соседей" in w.fake.prompts[-1]
    with sessions() as db:
        assert w.thread(db, nid).state == "resolved"


def test_model_failure_opens_the_thread_again(
    sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    w = World(sessions, tmp_path)
    w.fake.script = [AnalyzerError("claude -p: недоступен")]
    tid = w.accept("q1", "150")
    w.check(tid)
    with sessions() as db:
        assert w.thread(db, tid).state == "open"
        assert w.said(db, tid)[-1] == (
            "system",
            "Проверка ответа не удалась: claude -p: недоступен",
        )
    # A broken envelope: the same
    w.fake.script = [{"verdict": "maybe"}]
    with sessions() as db:
        thread = w.thread(db, tid)
        threads.accept(db, thread, threads.messages(db, thread)[0])
        db.commit()
    w.check(tid)
    with sessions() as db:
        author, text = w.said(db, tid)[-1]
        assert author == "system" and "verdict" in text
        assert w.thread(db, tid).state == "open"


def test_one_check_per_project_at_a_time(sessions: sessionmaker[Session], tmp_path: Path) -> None:
    """A thread accepted while another is being checked is queued, not run alongside, and not
    lost: the run goes on to it."""
    w = World(sessions, tmp_path)
    started: list[uuid.UUID] = []
    second: list[uuid.UUID] = []

    def accept_another() -> None:
        started.append(uuid.uuid4())
        if len(started) == 1:
            second.append(w.accept("q2", "ввод в коридоре", "installer"))
            w.check(second[0])  # the project is busy: only asks for one more pass
            assert len(w.fake.prompts) == 1  # not run inside

    w.fake.on_call = accept_another
    w.fake.script = [satisfied(None), satisfied(None)]
    first = w.accept("q1", "150")
    w.check(first)
    assert len(w.fake.prompts) == 2
    with sessions() as db:
        assert w.thread(db, first).state == "resolved"
        assert w.thread(db, second[0]).state == "resolved"
        assert next_checking(db, w.pid) is None
    assert w.rebuilt == [w.pid, w.pid]


def test_model_changed_during_the_check(sessions: sessionmaker[Session], tmp_path: Path) -> None:
    """Someone answered while the model thought: the check is run again on the new model; if the
    model keeps changing, the thread is given back."""
    w = World(sessions, tmp_path)

    def answer_q3() -> None:
        with sessions() as db:
            versions = w.versions(db)
            files = repo.model_files(versions[-1])
            files[ANSWERS_FILE] = f"answers:\n  q3: {4000 + len(versions)}\n"
            repo.add_model_version(db, w.pid, files, "user")
            db.commit()

    w.fake.on_call = answer_q3
    w.fake.script = [satisfied(None)] * 3
    tid = w.accept("q1", "150")
    w.check(tid)
    assert len(w.fake.prompts) == 3  # the first run and STALE_RUNS more
    with sessions() as db:
        assert w.thread(db, tid).state == "open"
        assert "Модель менялась" in w.said(db, tid)[-1][1]

    w.fake.on_call = None
    w.fake.script = [satisfied(None)]
    with sessions() as db:
        thread = w.thread(db, tid)
        threads.accept(db, thread, threads.messages(db, thread)[0])
        db.commit()
    w.check(tid)
    with sessions() as db:
        assert w.thread(db, tid).state == "resolved"


def test_recover_and_closed_meanwhile(sessions: sessionmaker[Session], tmp_path: Path) -> None:
    w = World(sessions, tmp_path)
    tid = w.accept("q1", "150")
    w.fake.script = [satisfied(None)]

    def close_it() -> None:  # the studio closed the thread while the model thought
        with sessions() as db:
            thread = w.thread(db, tid)
            thread.state, thread.accepted_message_id = "open", None
            threads.close(db, thread)
            db.commit()

    w.fake.on_call = close_it
    assert w.checks.recover() == [w.pid]
    with sessions() as db:
        assert w.thread(db, tid).state == "closed"
        assert len(w.versions(db)) == 1
        assert db.scalar(select(ThreadMessage.id).where(ThreadMessage.author == "analyzer")) is None
    assert w.rebuilt == []


def _wait(condition: Any, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def _state(w: World, thread_id: uuid.UUID) -> str:
    with w.sessions() as db:
        return w.thread(db, thread_id).state


def test_one_check_per_project_across_servers(
    sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    """Two servers on one database: while A checks the project, B does not; the thread accepted
    on B is checked by A."""
    w = World(sessions, tmp_path)
    gate, entered = threading.Event(), threading.Event()
    on_a = Fake([satisfied(None), satisfied(None)])

    def hold() -> None:
        entered.set()
        gate.wait(10)

    on_a.on_call = hold
    on_b = Fake([satisfied(None)])
    a = AnswerChecks(sessions, w.store, lambda: on_a, workers=2, rebuild=w._rebuild)
    b = AnswerChecks(sessions, w.store, lambda: on_b, workers=2, rebuild=w._rebuild)
    try:
        first = w.accept("q1", "150")
        a.check_thread(w.pid, first)
        assert entered.wait(10)
        second = w.accept("q2", "ввод в коридоре", "installer")
        b.check_thread(w.pid, second)
        b.join()
        assert b.run_project(w.pid) is False  # the lock is A's
        assert on_b.prompts == [] and _state(w, second) == "checking"
        gate.set()
        a.join()
        assert len(on_a.prompts) == 2
        assert (_state(w, first), _state(w, second)) == ("resolved", "resolved")
    finally:
        gate.set()
        a.stop()
        b.stop()


def test_dead_holder_releases_the_project(sessions: sessionmaker[Session], tmp_path: Path) -> None:
    """A server died holding the lock: its connection is gone, so the lock is too; the sweep
    (recover) of another server takes the thread."""
    w = World(sessions, tmp_path)
    dead = w.checks.engine.connect()
    key = func.hashtext(str(w.pid))
    assert dead.scalar(select(func.pg_try_advisory_lock(LOCK_CLASS, key)))
    tid = w.accept("q1", "150")
    w.fake.script = [satisfied(None)]
    w.check(tid)
    assert w.fake.prompts == [] and _state(w, tid) == "checking"
    dead.invalidate()  # the server process is gone: the database connection closes
    dead.close()
    assert w.checks.recover() == [w.pid]
    assert _state(w, tid) == "resolved"


def test_projects_are_checked_in_parallel(sessions: sessionmaker[Session], tmp_path: Path) -> None:
    one = World(sessions, tmp_path / "1")
    two = World(sessions, tmp_path / "2", slug="kv2")
    gate, entered = threading.Event(), threading.Event()

    @dataclass
    class Gated(Fake):
        def start(self, project: Path, prompt: str) -> Reply:
            if project.name == "kv":  # the first project waits
                entered.set()
                gate.wait(10)
            return self._next(prompt)

    fake = Gated([satisfied(None), satisfied(None)])
    checks = AnswerChecks(sessions, one.store, lambda: fake, workers=2, rebuild=one._rebuild)
    try:
        first = one.accept("q1", "150")
        checks.check_thread(one.pid, first)
        assert entered.wait(10)
        second = two.accept("q1", "120")
        checks.check_thread(two.pid, second)
        # The second project is done while the first still waits for its model
        assert _wait(lambda: _state(two, second) == "resolved")
        assert _state(one, first) == "checking"
        gate.set()
        checks.join()
        assert _state(one, first) == "resolved"
    finally:
        gate.set()
        checks.stop()


def test_sweep_finds_threads_nobody_queued(sessions: sessionmaker[Session], tmp_path: Path) -> None:
    """A thread left `checking` after start (its server died before queueing it) is found by the
    periodic sweep."""
    w = World(sessions, tmp_path)
    w.fake.script = [satisfied(None)]
    checks = AnswerChecks(sessions, w.store, lambda: w.fake, workers=1, rebuild=w._rebuild)
    checks.start(sweep_seconds=0.05)
    try:
        tid = w.accept("q1", "150")  # accepted, never submitted
        assert _wait(lambda: _state(w, tid) == "resolved")
    finally:
        checks.stop()
