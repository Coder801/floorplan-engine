"""A project folder ↔ the database (service/sync.py and `project`/`studio` commands): push makes a
version only for changed files, pull gives them back byte for byte with the latest build; neither
loses edits — a newer version in the database stops push, unpushed local edits stop pull."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from floorplan_engine.cli import app
from floorplan_engine.service import sync
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import access_codes
from floorplan_engine.service.db import repositories as repo
from floorplan_engine.service.db.models import AppUser, Build, Project, Studio
from floorplan_engine.service.objects import LocalObjectStore
from tests.electrical.test_variants import _project
from tests.service import conftest

CODE = "ABCD-2345"
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


def test_ensure_owner_creates_user_and_firm_once(db: Session) -> None:
    """The server start creates the owner and the firm if missing; the owner logging in later with
    the same confirmed e-mail is the same user."""
    studio = sync.ensure_owner(db, "Boss@Example.com")
    assert studio.kind == "studio" and studio.name == "Shtroba"
    assert sync.ensure_owner(db, "boss@example.com").id == studio.id  # once
    user = acc.oauth_login(db, "google", "g-1", "boss@example.com", True, "Boss")
    assert acc.own_studio(db, user) is not None and acc.own_studio(db, user).id == studio.id  # type: ignore[union-attr]
    by_phone = sync.ensure_owner(db, "+380 50 123 45 67")
    assert by_phone.id != studio.id


def test_import_only_new_keeps_the_database(
    pg: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Server start: projects and the studio price list already in the database are not
    overwritten by the image (the database is the truth); new ones are added."""
    monkeypatch.setenv("DATABASE_URL", conftest.test_database_url())
    monkeypatch.setenv("SHTROBA_OBJECTS", str(tmp_path / "store"))
    root = tmp_path / "seed"
    root.mkdir()
    _project(root)
    (root / "prices.yaml").write_text(STUDIO_PRICES, "utf-8")
    args = ["project", "import", str(root), "--owner", "boss@example.com", "--create-owner",
            "--only-new", "--no-build"]  # fmt: skip
    runner = CliRunner()
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    assert "kv: версия 1" in first.output
    (root / "kv" / "answers.yaml").write_text("answers: {}\n", "utf-8")  # git changed
    (root / "prices.yaml").write_text("currency: грн\nitems: {}\n", "utf-8")
    again = runner.invoke(app, args)
    assert "kv: уже в базе — пропущен" in again.output and "уже в базе" in again.output
    from floorplan_engine.service.db.session import make_sessions

    with make_sessions(pg)() as db:
        project = acc.project_by_slug(db, "kv")
        assert project is not None
        latest = repo.latest_model(db, project.id)
        assert latest is not None and latest.version == 1  # git did not overwrite the database
        studio = acc.own_studio(db, _owner(db))
        assert studio is not None
        files = sync.pull_studio(db, studio, tmp_path / "back")
        assert files == ["prices.yaml"]
        assert (tmp_path / "back" / "prices.yaml").read_text("utf-8") == STUDIO_PRICES


def _owner(db: Session) -> AppUser:
    from sqlalchemy import select

    user = db.scalar(select(AppUser).where(AppUser.email == "boss@example.com"))
    assert user is not None
    return user


def _import_args(root: Path, *more: str) -> list[str]:
    return ["project", "import", str(root), "--owner", "boss@example.com", "--create-owner",
            "--only-new", *more]  # fmt: skip


def _seed(root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", conftest.test_database_url())
    monkeypatch.setenv("SHTROBA_OBJECTS", str(tmp_path / "store"))
    root.mkdir()
    _project(root)


def test_import_only_new_fills_a_blank_row_of_the_studio(
    pg: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A row with only a name (a folder adopted on login, before projects moved to the database)
    is not "already in the database": the image fills it, the project keeps its id."""
    from floorplan_engine.service.db.session import make_sessions

    root = tmp_path / "seed"
    _seed(root, tmp_path, monkeypatch)
    with make_sessions(pg)() as db:
        project = Project(
            studio_id=sync.ensure_owner(db, "boss@example.com").id, name="kv", slug="kv"
        )
        db.add(project)
        db.commit()
        pid = project.id
    result = CliRunner().invoke(app, _import_args(root))
    assert result.exit_code == 0, result.output
    assert "kv: версия 1" in result.output and "сборка: built" in result.output
    with make_sessions(pg)() as db:
        rows = db.scalars(select(Project).where(Project.slug == "kv")).all()
        assert [p.id for p in rows] == [pid]
        assert repo.latest_model(db, pid) is not None


def test_import_only_new_moves_a_blank_unowned_row_to_the_owner(
    pg: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A row "no owner" made for an access code goes to the owner's studio; the code still works."""
    from floorplan_engine.service.db.session import make_sessions

    root = tmp_path / "seed"
    _seed(root, tmp_path, monkeypatch)
    with make_sessions(pg)() as db:
        blank = acc.create_project_unowned(db, "kv", "kv")
        access_codes.ensure_code(db, blank, CODE)
        db.commit()
        pid = blank.id
    result = CliRunner().invoke(app, _import_args(root))
    assert result.exit_code == 0, result.output
    with make_sessions(pg)() as db:
        project = db.get(Project, pid)
        assert project is not None and project.studio_id == acc.own_studio(db, _owner(db)).id  # type: ignore[union-attr]
        assert repo.latest_model(db, pid) is not None
        assert access_codes.use_code(db, CODE).project_id == pid


def test_import_only_new_merges_a_blank_duplicate_into_the_real_project(
    pg: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An earlier import made the project next to the blank "no owner" row: the blank row goes
    away and its code now opens the real project."""
    from floorplan_engine.service.db.session import make_sessions

    root = tmp_path / "seed"
    _seed(root, tmp_path, monkeypatch)
    runner = CliRunner()
    assert runner.invoke(app, _import_args(root, "--no-build")).exit_code == 0
    with make_sessions(pg)() as db:
        real = acc.project_by_slug(db, "kv")
        assert real is not None
        pid = real.id
        blank = acc.create_project_unowned(db, "kv", "kv")
        access_codes.ensure_code(db, blank, CODE)
        db.commit()
    result = runner.invoke(app, _import_args(root, "--no-build"))
    assert result.exit_code == 0, result.output
    assert "kv: уже в базе — пропущен" in result.output
    with make_sessions(pg)() as db:
        rows = db.scalars(select(Project).where(Project.slug == "kv")).all()
        assert [p.id for p in rows] == [pid]
        assert access_codes.use_code(db, CODE).project_id == pid
        latest = repo.latest_model(db, pid)
        assert latest is not None and latest.version == 1


def test_project_build_rebuilds_the_studio_projects(
    pg: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`project build`: the latest model version of each project of the studio, or of the named
    one; the model stays as it is, projects without a model are reported."""
    from floorplan_engine.service.db.session import make_sessions

    root = tmp_path / "seed"
    _seed(root, tmp_path, monkeypatch)
    runner = CliRunner()
    assert runner.invoke(app, _import_args(root)).exit_code == 0
    with make_sessions(pg)() as db:
        studio = sync.ensure_owner(db, "boss@example.com")
        db.add(Project(studio_id=studio.id, name="empty", slug="empty"))
        db.commit()
    args = ["project", "build", "--owner", "boss@example.com"]
    every = runner.invoke(app, args)
    assert every.exit_code == 0, every.output
    assert "kv: версия 1, сборка: built" in every.output and "empty: модели нет" in every.output
    one = runner.invoke(app, [*args, "kv"])
    assert "kv: версия 1" in one.output and "empty" not in one.output
    with make_sessions(pg)() as db:
        project = acc.project_by_slug(db, "kv")
        assert project is not None
        latest = repo.latest_model(db, project.id)
        assert latest is not None and latest.version == 1
        builds = db.scalars(select(Build).where(Build.model_version_id == latest.id)).all()
        assert len(builds) == 3
    missing = runner.invoke(app, [*args, "nope"])
    assert missing.exit_code == 1 and "Проекта nope" in missing.output
