"""Окружение Alembic: таблицы — из service/db/models.py, адрес — DATABASE_URL."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from shtroba.service.db.models import Base
from shtroba.service.db.session import database_url, make_engine

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

target_metadata = Base.metadata


def run_offline() -> None:
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    with make_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
