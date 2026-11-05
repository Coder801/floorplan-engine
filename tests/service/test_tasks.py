"""The task queue: order, errors, a worker that survives them, no threads with workers=0."""

from __future__ import annotations

import threading

from floorplan_engine.service.tasks import TaskQueue


def test_runs_submitted_tasks_on_workers() -> None:
    done: list[str] = []
    threads: set[str] = set()

    def run(project_id: str) -> None:
        done.append(project_id)
        threads.add(threading.current_thread().name)

    tasks = TaskQueue(run, workers=1)
    tasks.submit("a")
    tasks.submit("b")
    tasks.join()
    tasks.stop()
    assert done == ["a", "b"]
    assert threads == {"task-0"}


def test_no_workers_runs_inside_submit() -> None:
    done: list[str] = []
    tasks = TaskQueue(lambda project_id: done.append(project_id), workers=0)
    tasks.submit("a")
    assert done == ["a"]


def test_failed_task_does_not_kill_the_worker() -> None:
    done: list[str] = []

    def run(project_id: str) -> None:
        if project_id == "bad":
            raise OSError("диск заполнен")
        done.append(project_id)

    tasks = TaskQueue(run, workers=1)
    tasks.submit("bad")
    tasks.submit("good")
    tasks.join()
    tasks.stop()
    assert done == ["good"]


def test_stop_ends_workers_and_start_again_works() -> None:
    done: list[str] = []
    tasks = TaskQueue(lambda project_id: done.append(project_id), workers=2)
    tasks.start()
    tasks.stop()
    assert not [t for t in threading.enumerate() if t.name.startswith("task-")]
    tasks.submit("a")
    tasks.join()
    tasks.stop()
    assert done == ["a"]


def test_stop_does_not_start_what_waits_in_the_queue() -> None:
    done: list[str] = []
    running, release = threading.Event(), threading.Event()

    def run(project_id: str) -> None:
        running.set()
        release.wait(5)
        done.append(project_id)

    tasks = TaskQueue(run, workers=1)
    tasks.submit("first")
    running.wait(5)
    tasks.submit("waiting")
    threading.Timer(0.05, release.set).start()
    tasks.stop()
    assert done == ["first"]
