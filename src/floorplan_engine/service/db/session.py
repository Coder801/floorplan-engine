"""Подключение к базе: адрес — DATABASE_URL (см. .env.example), в тестах — SQLite в памяти."""

from __future__ import annotations

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from floorplan_engine.service.db.models import Base

DEFAULT_URL = (
    "postgresql+psycopg://floorplan_engine:floorplan_engine@localhost:5433/floorplan_engine"
)


def database_url() -> str:
    """Адрес базы; postgres:// и postgresql:// (так его даёт Railway) — через psycopg 3."""
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url())


def make_sessions(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def create_tables(engine: Engine) -> None:
    """Все таблицы разом — для тестов и пустой SQLite; в Postgres — миграции Alembic."""
    Base.metadata.create_all(engine)
