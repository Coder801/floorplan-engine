"""A project from the database (stage B, step B2; docs/database.md, "Переезд проектов из папок в
базу"): the core builds from a folder, so the service lays the latest model version out in a
temporary folder — the model files byte for byte, the project's own price list, and above the
project the price list and profile of its studio — runs build_project there and takes out/ into
file storage (build, build_file). The folder is deleted afterwards.

One build of a project at a time: a Postgres advisory lock by the project id, so it holds with
several servers too. Functions take an open Session and do not commit, like repositories.py.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from floorplan_engine.electrical.estimate import PRICES_FILE
from floorplan_engine.pipeline import OUT_DIR, AuditError, build_project
from floorplan_engine.service.db import repositories as repo
from floorplan_engine.service.db.models import (
    Build,
    BuildFile,
    ModelVersion,
    PriceList,
    Project,
    Source,
    StudioProfile,
)
from floorplan_engine.service.objects import ObjectStore, build_key
from floorplan_engine.validation.issues import STUDIO_FILE
from floorplan_engine.validation.report import REPORT_JSON

SOURCE_DIR = "source"
# File kinds of a build by extension, for build_file.kind
KINDS = {
    ".epd": "epd", ".dxf": "dxf", ".pdf": "pdf", ".png": "png", ".svg": "svg",
    ".xlsx": "xlsx", ".csv": "csv", ".md": "md", ".json": "json",
}  # fmt: skip


class NoModelError(LookupError):
    """The project has no model version yet: nothing to build."""


def lock(session: Session, project: Project) -> None:
    """Wait for other builds of this project (until the end of the transaction)."""
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(str(project.id)))))


def studio_files(session: Session, studio_id: uuid.UUID) -> dict[str, str]:
    """Files of a studio next to its project folders: prices.yaml (as written, with comments) and
    studio.yaml (the profile: organization, stage, signatures)."""
    files: dict[str, str] = {}
    prices = session.scalar(select(PriceList).where(PriceList.studio_id == studio_id))
    if prices is not None and prices.text:
        files[PRICES_FILE] = prices.text
    profile = session.get(StudioProfile, studio_id)
    if profile is not None:
        data: dict[str, Any] = {
            k: v
            for k, v in (
                ("organization", profile.organization),
                ("stage", profile.stage),
                ("signatures", profile.signatures),
            )
            if v
        }
        if data:
            files[STUDIO_FILE] = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return files


def project_files(
    session: Session, project: Project, version: ModelVersion | None = None
) -> dict[str, str]:
    """The project folder's own text files: the model files of a version (the latest by default)
    and the project's own price list."""
    version = version or repo.latest_model(session, project.id)
    if version is None:
        raise NoModelError(f"у проекта {project.slug or project.id} нет модели")
    files = repo.model_files(version)
    own = session.scalar(select(PriceList).where(PriceList.project_id == project.id))
    if own is not None and own.text:
        files[PRICES_FILE] = own.text
    return files


@contextmanager
def workdir(
    session: Session,
    store: ObjectStore,
    project: Project,
    version: ModelVersion | None = None,
    sources: bool = False,
) -> Iterator[Path]:
    """A temporary folder <tmp>/<studio>/<slug>/ with the project as the core expects it; with
    sources=True also source/ from file storage (the analyzer needs it, a build does not). The
    folder is removed on exit."""
    with tempfile.TemporaryDirectory(prefix="shtroba-") as tmp:
        studio_dir = Path(tmp) / "studio"
        folder = studio_dir / (project.slug or str(project.id))
        folder.mkdir(parents=True)
        for name, text in studio_files(session, project.studio_id).items():
            (studio_dir / name).write_text(text, "utf-8")
        for name, text in project_files(session, project, version).items():
            (folder / name).write_text(text, "utf-8")
        if sources:
            src = folder / SOURCE_DIR
            src.mkdir()
            for s in session.scalars(select(Source).where(Source.project_id == project.id)):
                (src / Path(s.object_key).name).write_bytes(store.get(s.object_key))
        yield folder


def build(
    session: Session, store: ObjectStore, project: Project, version: ModelVersion | None = None
) -> Build:
    """Build a model version (the latest by default): out/ goes into file storage under
    projects/<project>/builds/<build>/, the report into build.report. Status: built — sheets are
    there; insufficient — too little data, only the report; failed — the sheet check failed
    (the error is in the report). Waits for another build of the same project."""
    lock(session, project)
    version = version or repo.latest_model(session, project.id)
    if version is None:
        raise NoModelError(f"у проекта {project.slug or project.id} нет модели")
    row = Build(model_version_id=version.id, status="failed", report={})
    session.add(row)
    session.flush()
    with workdir(session, store, project, version) as folder:
        try:
            result = build_project(folder)
            row.status = "built" if result.built else "insufficient"
        except AuditError as exc:
            row.report = {"error": str(exc)}
        out = folder / OUT_DIR
        report = out / REPORT_JSON
        if report.is_file():
            row.report = {**json.loads(report.read_text("utf-8")), **row.report}
        for path in sorted(p for p in out.rglob("*") if p.is_file()):
            rel = path.relative_to(out).as_posix()
            key = build_key(project.id, row.id, rel)
            store.put(key, path.read_bytes())
            session.add(
                BuildFile(
                    build_id=row.id,
                    kind=KINDS.get(path.suffix.lower(), "file"),
                    name=rel,
                    object_key=key,
                )
            )
    session.flush()
    return row


def latest_build(session: Session, project: Project) -> Build | None:
    """The newest build of the project (any status)."""
    return session.scalar(
        select(Build)
        .join(ModelVersion, ModelVersion.id == Build.model_version_id)
        .where(ModelVersion.project_id == project.id)
        .order_by(Build.created_at.desc())
        .limit(1)
    )


def build_file(session: Session, build: Build, name: str) -> BuildFile | None:
    """A file of a build by its path inside out/ (project.epd, estimate.xlsx…)."""
    return session.scalar(
        select(BuildFile).where(BuildFile.build_id == build.id, BuildFile.name == name)
    )
