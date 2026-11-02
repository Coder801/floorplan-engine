"""База для тестов сервиса — Postgres, тот же движок, что на сервере (решение 2026-11-01:
SQLite в проекте нет). Отдельная база TEST_DATABASE_URL (по умолчанию floorplan_engine_test
на Postgres из docker-compose.yml); имя обязано кончаться на «_test»: база пересоздаётся
на каждый прогон. Схему строят миграции Alembic (вверх, вниз до нуля и снова вверх — так
проверяются и они), после каждого теста таблицы очищаются.

Postgres не запущен — тесты базы пропускаются с подсказкой; TEST_REQUIRE_DB=1 (CI) —
вместо пропуска ошибка.
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
    """Миграции Alembic на этой базе (migrations/env.py берёт соединение из attributes)."""
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
    migrate(engine, "base", down=True)  # откат каждой миграции
    migrate(engine, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def pg(pg_engine: Engine) -> Iterator[Engine]:
    """Чистая база на тест: после теста все таблицы очищаются."""
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
