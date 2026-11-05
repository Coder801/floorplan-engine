"""Background work of the service: a queue of project ids and worker threads.

The queue itself keeps no state: what to do is in the project (`ProjectInfo.task`, written to
service.json together with the busy state), so a restart loses nothing — Workflow.recover finds
busy projects and puts them back. Here there is no Workflow, only "run this project".
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable

WORKERS = 2  # projects processed at once: every one may hold an LLM call or a full build
log = logging.getLogger(__name__)


class TaskQueue:
    """`workers=0` runs a task right in `submit`: no threads (tests, one-off scripts)."""

    def __init__(self, run: Callable[[str], None], workers: int = WORKERS) -> None:
        self._run = run
        self._workers = workers
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._stopping = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        if self._threads:
            return
        self._stopping.clear()
        self._threads = [
            threading.Thread(target=self._loop, name=f"task-{n}", daemon=True)
            for n in range(self._workers)
        ]
        for thread in self._threads:
            thread.start()

    def submit(self, project_id: str) -> None:
        if self._workers == 0:
            self._safe_run(project_id)
            return
        self.start()
        self._queue.put(project_id)

    def join(self) -> None:
        """Wait until everything submitted is done."""
        self._queue.join()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the workers without taking anything new: what waits in the queue, and a worker
        busy past the timeout, die with the process, and their tasks in service.json come back on
        the next start."""
        self._stopping.set()
        threads, self._threads = self._threads, []
        for _ in threads:
            self._queue.put(None)
        for thread in threads:
            thread.join(timeout)

    def _loop(self) -> None:
        while True:
            project_id = self._queue.get()
            try:
                if project_id is None:
                    return
                if not self._stopping.is_set():
                    self._safe_run(project_id)
            finally:
                self._queue.task_done()

    def _safe_run(self, project_id: str) -> None:
        # Whatever gets past Workflow must not kill the worker
        try:
            self._run(project_id)
        except Exception:
            log.exception("задача проекта %s", project_id)
