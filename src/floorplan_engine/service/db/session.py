"""Database connection (Postgres only): the URL is DATABASE_URL (see .env.example); the schema is
built by Alembic migrations, in tests by tests/service/conftest.py."""

from __future__ import annotations

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_URL = (
    "postgresql+psycopg://floorplan_engine:floorplan_engine@localhost:5433/floorplan_engine"
)


def database_url() -> str:
    """Database URL; postgres:// and postgresql:// (as Railway gives it) go through psycopg 3."""
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url())


def make_sessions(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
