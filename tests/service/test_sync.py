"""A project folder ↔ the database (service/sync.py and `project`/`studio` commands): push makes a
version only for changed files, pull gives them back byte for byte with the latest build; neither
loses edits — a newer version in the database stops push, unpushed local edits stop pull."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from floorplan_engine.cli import app
from floorplan_engine.service import sync
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import repositories as repo
from floorplan_engine.service.db.models import Studio
from floorplan_engine.service.objects import LocalObjectStore
from tests.electrical.test_variants import _project
from tests.service import conftest

STUDIO_PRICES = "# студия\ncurrency: грн\nitems:\n  work.chase: 321\n"


def _studio(db: Session) -> Studio:
    owner = acc.oauth_login(db, "google", "o", "owner@example.com", True, "Owner")
    return acc.register_firm(db, owner, "Искра", "electric")


def _folder(tmp_path: Path) -> Path:
    folder = _project(tmp_path)
    (folder / "source").mkdir()
    (folder / "source" / "План.pdf").write_bytes(b"%PDF-1")
    return folder


def test_push_new_project_then_only_changes(db: Session, tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    folder = _folder(tmp_path)
    with pytest.raises(sync.SyncError, match="укажите студию"):
        sync.push(db, store, folder)
    studio = _studio(db)
    first = sync.push(db, store, folder, studio)
    assert (first.version, first.new_version, first.sources) == (1, True, ["План.pdf"])
    assert first.project.slug == "kv" and first.project.name == "Кв"  # name from room.yaml
    assert first.build is not None and first.build.status == "built"
    assert sync.read_marker(folder) == sync.Marker(first.project.id, 1)

    again = sync.push(db, store, folder)
    assert (again.version, again.new_version, again.sources, again.build) == (1, False, [], None)
    (folder / "answers.yaml").write_text("answers: {}\n", "utf-8")
    third = sync.push(db, store, folder)
    assert (third.version, third.new_version) == (2, True)

    other = tmp_path / "copy" / "kv"
    shutil.copytree(folder, other, ignore=shutil.ignore_patterns(".shtroba.yaml"))
    with pytest.raises(sync.SyncError, match="уже в студии"):
        sync.push(db, store, other, studio)


def test_pull_round_trip_and_conflicts(db: Session, tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    folder = _folder(tmp_path)
    pushed = sync.push(db, store, folder, _studio(db))
    project = pushed.project

    copy = tmp_path / "pulled" / "kv"
    assert sync.pull(db, store, project, copy) == 1
    assert sync.model_files(copy) == sync.model_files(folder)  # byte for byte
    assert (copy / "source" / "План.pdf").read_bytes() == b"%PDF-1"
    assert (copy / "out" / "project.epd").is_file()

    # A route edit on the server: a newer version in the database stops push from the old copy
    files = {**repo.model_files(repo.latest_model(db, project.id)), "wiring.yaml": "wires: {}\n"}  # type: ignore[arg-type]
    repo.add_model_version(db, project.id, files, "user")
    (folder / "answers.yaml").write_text("answers: {}\n", "utf-8")
    with pytest.raises(sync.SyncError, match="сначала project pull"):
        sync.push(db, store, folder)
    # …and pull does not overwrite the unpushed edit without force
    with pytest.raises(sync.SyncError, match="есть правки"):
        sync.pull(db, store, project, folder)
    assert sync.pull(db, store, project, folder, force=True) == 2
    assert (folder / "wiring.yaml").read_text("utf-8") == "wires: {}\n"
    assert not (folder / "answers.yaml").exists()  # not in the latest version
    assert sync.push(db, store, folder).new_version is False


def test_studio_files_round_trip(db: Session, tmp_path: Path) -> None:
    studio = _studio(db)
    root = tmp_path / "projects"
    root.mkdir()
    (root / "prices.yaml").write_text(STUDIO_PRICES, "utf-8")
    (root / "studio.yaml").write_text("organization: Искра\nstage: Р\n", "utf-8")
    assert sync.push_studio(db, studio, root) == ["prices.yaml", "studio.yaml"]
    back = tmp_path / "back"
    assert sync.pull_studio(db, studio, back) == ["prices.yaml", "studio.yaml"]
    assert (back / "prices.yaml").read_text("utf-8") == STUDIO_PRICES  # comments kept
    assert "stage: Р" in (back / "studio.yaml").read_text("utf-8")


def test_import_and_pull_commands(
    pg: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", conftest.test_database_url())
    monkeypatch.setenv("SHTROBA_OBJECTS", str(tmp_path / "store"))
    from floorplan_engine.service.db.session import make_sessions

    with make_sessions(pg)() as db:
        _studio(db)
        db.commit()
    root = tmp_path / "projects"
    root.mkdir()
    _project(root)
    (root / "prices.yaml").write_text(STUDIO_PRICES, "utf-8")
    runner = CliRunner()
    result = runner.invoke(app, ["project", "import", str(root), "--owner", "owner@example.com"])
    assert result.exit_code == 0, result.output
    assert "Студия «Искра»: prices.yaml" in result.output and "kv: версия 1" in result.output
    again = runner.invoke(app, ["project", "import", str(root), "--owner", "owner@example.com"])
    assert "kv: без изменений (версия 1)" in again.output
    pulled = runner.invoke(app, ["project", "pull", "kv", "--to", str(tmp_path / "out")])
    assert pulled.exit_code == 0 and (tmp_path / "out" / "kv" / "room.yaml").is_file()
    missing = runner.invoke(app, ["project", "pull", "nope", "--to", str(tmp_path / "out")])
    assert missing.exit_code == 1


def test_same_folder_name_in_two_studios(db: Session, tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    first = _studio(db)
    other = acc.oauth_login(db, "google", "x", "x@example.com", True, "X")
    second = acc.register_firm(db, other, "Другая", "design")
    for d in "abc":
        (tmp_path / d).mkdir()
    a = sync.push(db, store, _project(tmp_path / "a"), first, build=False)
    b = sync.push(db, store, _project(tmp_path / "b"), second, build=False)
    assert a.project.slug == b.project.slug == "kv" and a.project.id != b.project.id
    with pytest.raises(sync.SyncError, match="уже в студии"):
        sync.push(db, store, _project(tmp_path / "c"), first)
