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

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from floorplan_engine.service.db.models import Base
from floorplan_engine.service.db.session import make_engine, make_sessions

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
