"""File storage by key (decision 2026-11-03, docs/database.md, "Переезд проектов из папок в базу"):
sources, built sheets, DXF and estimates are addressed by a key written in the database, not by a
project folder. For now one implementation — a folder on the server volume (LocalObjectStore);
R2/S3 will be a second one behind the same protocol.

Keys are slash-separated paths of safe segments: `projects/<project id>/sources/<sha256>/plan.pdf`,
`projects/<project id>/builds/<build id>/project.epd` (source_key, build_key).
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Protocol

SEGMENT = re.compile(r"^[\w.\- ()]+$")


class ObjectKeyError(ValueError):
    """A key that is not a safe relative path."""


def check_key(key: str) -> str:
    """The key itself if every segment is a plain name: no empty segments, no "." or "..", no
    leading slash or backslash — a key never leaves its storage."""
    parts = key.split("/")
    if not key or any(p in {"", ".", ".."} or not SEGMENT.match(p) for p in parts):
        raise ObjectKeyError(f"недопустимый ключ файла: {key!r}")
    return key


def safe_name(name: str) -> str:
    """A file name as a key segment: characters outside letters, digits, ".-_ ()" become "_"."""
    clean = re.sub(r"[^\w.\- ()]", "_", Path(name).name).strip(" .")
    return clean or "file"


def source_key(project_id: uuid.UUID, sha256: str, name: str) -> str:
    return check_key(f"projects/{project_id}/sources/{sha256}/{safe_name(name)}")


def build_prefix(project_id: uuid.UUID, build_id: uuid.UUID) -> str:
    return check_key(f"projects/{project_id}/builds/{build_id}")


def build_key(project_id: uuid.UUID, build_id: uuid.UUID, rel: str) -> str:
    return check_key(f"{build_prefix(project_id, build_id)}/{rel}")


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete_prefix(self, prefix: str) -> None: ...
    def local_path(self, key: str) -> Path | None:
        """The file on this machine, to serve it without reading into memory; None for remote
        storage (then the API serves get() or a signed link)."""
        ...


class LocalObjectStore:
    """Objects as files under root: root/<key>. Writing goes through a temporary file and a
    rename, so a reader never sees half a file."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / check_key(key)

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(f"нет файла {key}")
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete_prefix(self, prefix: str) -> None:
        """Delete everything under a key prefix (a project, a build)."""
        base = self._path(prefix.rstrip("/"))
        if base.is_file():
            base.unlink()
            return
        if base.is_dir():
            for p in sorted(base.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                p.unlink() if p.is_file() else p.rmdir()
            base.rmdir()

    def local_path(self, key: str) -> Path | None:
        path = self._path(key)
        return path if path.is_file() else None


OBJECTS_ENV = "SHTROBA_OBJECTS"  # folder of the file storage; default data/objects


def store_from_env(env: dict[str, str] | None = None) -> LocalObjectStore:
    """File storage of this server: a folder from SHTROBA_OBJECTS (on Railway — on the volume)."""
    env = dict(os.environ) if env is None else env
    return LocalObjectStore(Path(env.get(OBJECTS_ENV, "data/objects")))
