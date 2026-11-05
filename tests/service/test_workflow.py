"""Tasks in the project state: a restart picks up cut-off work and does not repeat it for ever."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from floorplan_engine.service.analysis.analyzer import AnalysisResult, ManualAnalyzer
from floorplan_engine.service.models import PendingTask, ProjectState
from floorplan_engine.service.storage import Storage
from floorplan_engine.service.workflow import MAX_ATTEMPTS, ConflictError, Workflow


class Crash(BaseException):
    """The process dies in the middle of the work: nothing in Workflow may catch this."""


class CrashingAnalyzer(ManualAnalyzer):
    def analyze(self, project: Path, round_no: int) -> AnalysisResult:
        raise Crash


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "data")


def _project(storage: Storage) -> str:
    return storage.create("Кухня", [("plan.pdf", b"%PDF-1.4 test")]).id


def test_start_saves_the_task_with_the_busy_state(storage: Storage) -> None:
    flow = Workflow(storage, ManualAnalyzer())
    pid = _project(storage)
    flow.start_analysis(pid)
    info = storage.load(pid)
    assert info.state is ProjectState.ANALYZING
    assert info.task == PendingTask(kind="analysis")
    with pytest.raises(ConflictError):
        flow.start_analysis(pid)


def test_finished_task_is_cleared(storage: Storage) -> None:
    flow = Workflow(storage, ManualAnalyzer())
    pid = _project(storage)
    flow.start_analysis(pid)
    flow.run_task(pid)
    info = storage.load(pid)
    assert not info.state.busy
    assert info.task is None
    assert flow.recover() == []


def test_run_without_task_does_nothing(storage: Storage) -> None:
    pid = _project(storage)
    before = storage.load(pid)
    Workflow(storage, ManualAnalyzer()).run_task(pid)
    assert storage.load(pid) == before


def test_crash_leaves_the_task_for_recover_with_limited_attempts(storage: Storage) -> None:
    flow = Workflow(storage, CrashingAnalyzer())
    pid = _project(storage)
    flow.start_analysis(pid)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        assert flow.recover() == [pid]  # the service came back, the work goes on
        with pytest.raises(Crash):
            flow.run_task(pid)
        info = storage.load(pid)
        assert info.state is ProjectState.ANALYZING
        assert info.task is not None and info.task.attempts == attempt
    assert flow.recover() == []  # used up: no more tokens on this task
    info = storage.load(pid)
    assert info.state is ProjectState.FAILED
    assert info.task is None and "перезапуском" in info.message


def test_busy_state_without_a_task_fails_on_recover(storage: Storage) -> None:
    """service.json written before tasks were saved."""
    pid = _project(storage)
    info = storage.load(pid)
    info.state = ProjectState.BUILDING
    storage.save(info)
    assert Workflow(storage, ManualAnalyzer()).recover() == []
    assert storage.load(pid).state is ProjectState.FAILED


def test_failed_project_can_be_started_again(storage: Storage) -> None:
    flow = Workflow(storage, CrashingAnalyzer())
    pid = _project(storage)
    info = storage.load(pid)
    info.state = ProjectState.FAILED
    storage.save(info)
    assert flow.start_analysis(pid).state is ProjectState.ANALYZING


def test_a_double_click_starts_one_task(storage: Storage) -> None:
    flow = Workflow(storage, ManualAnalyzer())
    pid = _project(storage)
    barrier = threading.Barrier(8)
    won: list[int] = []

    def click() -> None:
        barrier.wait()
        try:
            flow.start_analysis(pid)
            won.append(1)
        except ConflictError:
            pass

    threads = [threading.Thread(target=click) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(won) == 1


def test_interrupted_answers_keep_the_round(storage: Storage) -> None:
    flow = Workflow(storage, CrashingAnalyzer())
    pid = _project(storage)
    info = storage.load(pid)
    info.round = 1
    info.state = ProjectState.BUILDING
    info.task = PendingTask(kind="answers", has_text=True)
    storage.save(info)
    with pytest.raises(Crash):
        flow.run_task(pid)
    saved = storage.load(pid)
    assert saved.round == 1  # the crash saved nothing: the repeat counts the round once
    assert saved.task is not None and saved.task.attempts == 1 and saved.task.has_text


def test_a_failed_save_does_not_leave_the_project_busy(
    storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    flow = Workflow(storage, ManualAnalyzer())
    pid = _project(storage)
    flow.start_analysis(pid)

    def broken(_: str) -> None:
        raise OSError("диск заполнен")

    monkeypatch.setattr(flow, "run_analysis", broken)
    flow.run_task(pid)
    info = storage.load(pid)
    assert info.state is ProjectState.FAILED and info.task is None
    assert "диск заполнен" in info.message


def test_a_broken_project_does_not_stop_the_start(storage: Storage) -> None:
    good = _project(storage)
    broken = _project(storage)
    (storage.root / broken / "service.json").write_text("{", encoding="utf-8")
    assert [p.id for p in storage.list()] == [good]
    assert Workflow(storage, ManualAnalyzer()).recover() == []
