"""Service project storage on the file system.

A project is the same folder as for the CLI (`intake.yaml`, `room.yaml`, `answers.yaml`,
`source/`, `out/`), plus:

    service.json         project state (ProjectInfo)
    rounds/NNN/          a question round: answers.json (what was sent), report.json (result)

Later a database and object storage will take this place behind the same interface.
"""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from floorplan_engine.service.analysis.analyzer import OPERATOR_FILES
from floorplan_engine.service.models import ProjectInfo, ProjectState

STATE_FILE = "service.json"
SOURCE_DIR = "source"
ROUNDS_DIR = "rounds"


class NotFoundError(LookupError):
    pass


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Storage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def lock(self, project_id: str) -> threading.Lock:
        """One process per project at a time: analysis, answers, build."""
        with self._guard:
            return self._locks.setdefault(project_id, threading.Lock())

    def path(self, project_id: str) -> Path:
        path = self.root / project_id
        # id is hex from uuid4 only: the path cannot escape root
        if not project_id.isalnum() or not (path / STATE_FILE).exists():
            raise NotFoundError(project_id)
        return path

    def create(self, name: str, sources: list[tuple[str, bytes]]) -> ProjectInfo:
        project_id = uuid.uuid4().hex
        path = self.root / project_id
        (path / SOURCE_DIR).mkdir(parents=True)
        names = []
        for filename, content in sources:
            safe = Path(filename).name or "file"
            if safe in OPERATOR_FILES:  # ready model goes to the project folder
                (path / safe).write_bytes(content)
                continue
            (path / SOURCE_DIR / safe).write_bytes(content)
            names.append(f"{SOURCE_DIR}/{safe}")
        info = ProjectInfo(
            id=project_id,
            name=name,
            state=ProjectState.CREATED,
            created=now(),
            updated=now(),
            sources=names,
        )
        self.save(info)
        return info

    def load(self, project_id: str) -> ProjectInfo:
        text = (self.path(project_id) / STATE_FILE).read_text(encoding="utf-8")
        return ProjectInfo.model_validate_json(text)

    def save(self, info: ProjectInfo) -> None:
        info.updated = now()
        path = self.root / info.id / STATE_FILE
        tmp = path.with_suffix(".tmp")
        tmp.write_text(info.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)  # atomic: a reader never sees half a file

    def list(self) -> list[ProjectInfo]:
        infos = [
            ProjectInfo.model_validate_json((p / STATE_FILE).read_text(encoding="utf-8"))
            for p in self.root.iterdir()
            if (p / STATE_FILE).exists()
        ]
        return sorted(infos, key=lambda i: i.created, reverse=True)

    def delete(self, project_id: str) -> None:
        """Delete the whole project: sources, model, results, rounds."""
        path = self.path(project_id)
        with self.lock(project_id):
            shutil.rmtree(path)
        with self._guard:
            self._locks.pop(project_id, None)

    def write_model(self, project_id: str, filename: str, text: str) -> None:
        (self.path(project_id) / filename).write_text(text, encoding="utf-8")

    def save_round(self, project_id: str, round_no: int, name: str, data: Any) -> None:
        folder = self.path(project_id) / ROUNDS_DIR / f"{round_no:03d}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
