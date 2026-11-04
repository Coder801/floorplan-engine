"""A project from the database (service/project_store.py): the latest model version is laid out in
a temporary folder with its studio's price list and profile, built by the core, and out/ goes into
file storage with build and build_file rows."""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from floorplan_engine.service import project_store as ps
from floorplan_engine.service.db import repositories as repo
from floorplan_engine.service.db.models import (
    Build,
    BuildFile,
    PriceList,
    Source,
    StudioProfile,
)
from floorplan_engine.service.objects import (
    LocalObjectStore,
    build_key,
    build_prefix,
    source_key,
)
from tests.electrical.test_variants import _project

PRICES = "# прайс студии\ncurrency: грн\nitems:\n  work.chase: 321  # штроба\n"


def _files(folder: Path) -> dict[str, str]:
    return {p.name: p.read_text("utf-8") for p in folder.glob("*.yaml")}


def test_workdir_lays_out_model_studio_and_sources(db: Session, tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    studio = repo.create_studio(db, "Искра")
    project = repo.create_project(db, studio.id, "Кв")
    project.slug = "kv"
    files = _files(_project(tmp_path))
    repo.add_model_version(db, project.id, files, "operator")
    db.add(PriceList(studio_id=studio.id, text=PRICES))
    db.add(StudioProfile(studio_id=studio.id, organization="Искра", stage="Р"))
    key = source_key(project.id, "ab", "План.pdf")
    store.put(key, b"%PDF")
    db.add(
        Source(
            project_id=project.id, file_name="План.pdf", sha256="ab", kind="vector", object_key=key
        )
    )
    db.flush()
    with ps.workdir(db, store, project, sources=True) as folder:
        assert folder.name == "kv"
        assert _files(folder) == files  # byte for byte
        assert (folder.parent / "prices.yaml").read_text("utf-8") == PRICES  # with comments
        assert "organization: Искра" in (folder.parent / "studio.yaml").read_text("utf-8")
        assert (folder / "source" / "План.pdf").read_bytes() == b"%PDF"
        kept = folder
    assert not kept.exists()  # removed after use


def test_only_the_last_builds_stay(db: Session, tmp_path: Path) -> None:
    """Old builds go with their rows and files; the model version stays."""
    store = LocalObjectStore(tmp_path / "objects")
    studio = repo.create_studio(db, "Искра")
    project = repo.create_project(db, studio.id, "Кв")
    repo.add_model_version(db, project.id, _files(_project(tmp_path)), "operator")
    db.add(PriceList(studio_id=studio.id, text=PRICES))
    db.flush()
    builds = [ps.build(db, store, project) for _ in range(ps.KEEP_BUILDS + 2)]
    left = list(db.scalars(select(Build.id)))
    assert len(left) == ps.KEEP_BUILDS and builds[-1].id in left
    kept = [b for b in builds if b.id in left]
    for build in kept:
        assert store.exists(build_key(project.id, build.id, "project.epd"))
    gone = [b.id for b in builds if b.id not in left]
    for build_id in gone:
        assert not (store.root / build_prefix(project.id, build_id)).exists()
    assert not db.scalar(select(BuildFile.id).where(BuildFile.build_id.in_(gone)))
    assert repo.latest_model(db, project.id) is not None


def test_build_puts_out_into_storage(db: Session, tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    studio = repo.create_studio(db, "Искра")
    project = repo.create_project(db, studio.id, "Кв")
    with pytest.raises(ps.NoModelError):
        ps.build(db, store, project)
    repo.add_model_version(db, project.id, _files(_project(tmp_path)), "operator")
    db.add(PriceList(studio_id=studio.id, text=PRICES))
    db.flush()

    build = ps.build(db, store, project)
    assert build.status == "built" and build.report["stages"]
    names = {f.name for f in build.files}
    assert {"project.epd", "project.dxf", "report.json", "estimate.csv"} <= names
    epd = ps.build_file(db, build, "project.epd")
    assert epd is not None and epd.kind == "epd"
    with zipfile.ZipFile(BytesIO(store.get(epd.object_key))) as zf:
        assert "manifest.json" in zf.namelist()
    estimate = ps.build_file(db, build, "estimate.csv")
    assert estimate is not None and "321" in store.get(estimate.object_key).decode()  # studio price
    assert ps.latest_build(db, project) is build


def test_too_little_data_is_insufficient(db: Session, tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    project = repo.create_project(db, repo.create_studio(db, "С").id, "Пусто")
    repo.add_model_version(db, project.id, {"intake.yaml": "sources: []\nquestions: []\n"}, "user")
    build = ps.build(db, store, project)
    assert build.status == "insufficient"
    assert ps.build_file(db, build, "project.epd") is None
    assert ps.build_file(db, build, "report.md") is not None
