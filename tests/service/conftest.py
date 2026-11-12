"""Database for service tests: Postgres, the same engine as on the server (decision 2026-11-01:
no SQLite in the project). A separate database TEST_DATABASE_URL (by default
floorplan_engine_test on the Postgres from docker-compose.yml); the name must end in "_test":
the database is recreated on every run. The schema is built by Alembic migrations (up, down
to zero and up again, which tests them too), and tables are cleared after each test.

If Postgres is not running, database tests are skipped with a hint; TEST_REQUIRE_DB=1 (CI)
turns the skip into an error.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from floorplan_engine.service.db import repositories as repo
from floorplan_engine.service.db import work
from floorplan_engine.service.db import work_records as records
from floorplan_engine.service.db.models import (
    AppUser,
    Base,
    Build,
    Membership,
    ProjectMember,
    WorkPlan,
    WorkTask,
)
from floorplan_engine.service.db.session import make_engine, make_sessions
from floorplan_engine.service.objects import LocalObjectStore

TEST_URL = (
    "postgresql+psycopg://floorplan_engine:floorplan_engine@localhost:5433/floorplan_engine_test"
)
HINT = "Postgres для тестов не запущен: docker compose up -d db"


def test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", TEST_URL)


def migrate(engine: Engine, revision: str, down: bool = False) -> None:
    """Alembic migrations on this database (migrations/env.py takes the connection from
    attributes).
    """
    cfg = Config("alembic.ini")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        (command.downgrade if down else command.upgrade)(cfg, revision)


@pytest.fixture(scope="session")
def pg_engine() -> Iterator[Engine]:
    url = make_url(test_database_url())
    name = url.database or ""
    if not name.endswith("_test"):
        raise pytest.UsageError(f"TEST_DATABASE_URL: база {name!r} — не тестовая (нужно *_test)")
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as exc:
        if os.environ.get("TEST_REQUIRE_DB") == "1":
            raise
        pytest.skip(f"{HINT} ({exc.orig.__class__.__name__})")
    finally:
        admin.dispose()
    engine = make_engine(url.render_as_string(hide_password=False))
    migrate(engine, "head")
    migrate(engine, "base", down=True)  # downgrade of every migration
    migrate(engine, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def pg(pg_engine: Engine) -> Iterator[Engine]:
    """A clean database per test: all tables are cleared after the test."""
    yield pg_engine
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with pg_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def sessions(pg: Engine) -> sessionmaker[Session]:
    return make_sessions(pg)


@pytest.fixture
def db(sessions: sessionmaker[Session]) -> Iterator[Session]:
    with sessions() as s:
        yield s


# --- Installation by tasks (db/work.py, db/work_records.py): a project with a plan draft ------

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def draft_line(key: str, kind: str, qty: float, price: float | None) -> dict[str, Any]:
    return {
        "key": key,
        "kind": kind,
        "title": key or "Своя",
        "unit": "м",
        "qty": qty,
        "price": price,
    }


DRAFT: dict[str, Any] = {
    "currency": "грн",
    "tasks": [
        {
            "key": "electrical.chases",
            "domain": "electrical",
            "order": 1,
            "title": "Штробы",
            "after": [],
            "photo": "optional",
            "result": ["штроба выбрана"],
            "lines": [
                draft_line("work.chase.brick", "work", 10.0, 120.0),
                draft_line("socket_box", "material", 4.0, 15.0),
            ],
        },
        {
            "key": "electrical.cable",
            "domain": "electrical",
            "order": 2,
            "title": "Прокладка кабеля",
            "after": ["electrical.chases"],
            "photo": "required",
            "result": ["кабель закреплён"],
            "lines": [
                draft_line("work.cable", "work", 100.0, 34.0),
                draft_line("cable.3x1.5", "material", 110.0, None),
            ],
        },
    ],
}


class World:
    """A studio project with a build row, its people as actors, and file storage."""

    def __init__(self, db: Session, tmp_path: Path) -> None:
        self.db = db
        self.store = LocalObjectStore(tmp_path / "store")
        studio = repo.create_studio(db, "Искра")
        self.project = repo.create_project(db, studio.id, "Кв")
        version = repo.add_model_version(db, self.project.id, {"room.yaml": "x: 1\n"}, "user")
        self.build = Build(model_version_id=version.id, status="built", report={})
        users = {n: AppUser(email=f"{n}@example.com", name=n.title()) for n in ("a", "i", "c")}
        db.add_all([self.build, *users.values()])
        db.flush()
        db.add(Membership(studio_id=studio.id, user_id=users["a"].id, role="owner"))
        db.add(ProjectMember(project_id=self.project.id, user_id=users["i"].id, role="installer"))
        db.flush()
        self.users = users
        self.owner = work.Actor("owner", users["a"], "A")
        self.installer = work.Actor("installer", users["i"], "I")
        self.client = work.Actor("client", users["c"], "C")
        self.code = work.Actor("client_code", None, "код: Иван")
        self.viewer = work.Actor("viewer", None, "код доступа")

    def plan(self) -> WorkPlan:
        plan = work.current_plan(self.db, self.project)
        assert plan is not None
        return plan

    def approved(self) -> tuple[WorkPlan, WorkTask, WorkTask]:
        work.create_plan(self.db, self.project, self.build, DRAFT, self.owner)
        work.plan_action(self.db, self.project, self.plan(), "propose", self.owner)
        work.plan_action(self.db, self.project, self.plan(), "approve", self.client)
        plan = self.plan()
        return plan, plan.tasks[0], plan.tasks[1]

    def status(
        self,
        task: WorkTask,
        to: str,
        actor: work.Actor,
        comment: str | None = None,
        body: dict[str, Any] | None = None,
    ) -> None:
        work.change_status(self.db, self.project, self.plan(), task, to, comment, actor, body)

    def photo(self, task: WorkTask, actor: work.Actor, data: bytes = PNG) -> None:
        records.add_photo(
            self.db,
            self.store,
            self.project,
            self.plan(),
            task,
            data,
            "a.png",
            "image/png",
            "",
            actor,
        )


@pytest.fixture
def world(db: Session, tmp_path: Path) -> World:
    return World(db, tmp_path)


@contextmanager
def fails(status: int, match: str = "") -> Iterator[None]:
    """A broken rule of db/work.py: a WorkError with this HTTP status and text."""
    with pytest.raises(work.WorkError) as info:
        yield
    assert info.value.status == status, (info.value.status, str(info.value))
    assert match in str(info.value)
