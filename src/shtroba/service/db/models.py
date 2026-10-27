"""Таблицы базы сервиса (SQLAlchemy 2): Postgres в работе, SQLite в тестах.

Схема — как на ER-диаграмме в docs/database.md. YAML остаётся форматом модели проекта:
база хранит его версии (model_version), а ядро по-прежнему собирает чертёж из папки.
Файлы (источники, DXF, .epd, PNG, образцы УГО) — в объектном хранилище: в базе только ключ
object_key.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# JSON: в Postgres — jsonb (индексы и запросы внутрь), в SQLite — текст с JSON
Json = JSON().with_variant(JSONB(), "postgresql")


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: Json, list[Any]: Json}


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=now)


# --- Студии и доступ --------------------------------------------------------------


class Studio(Base):
    __tablename__ = "studio"
    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()
    profile: Mapped[StudioProfile | None] = relationship(back_populates="studio")
    projects: Mapped[list[Project]] = relationship(back_populates="studio")


class AppUser(Base):
    """Пользователь (user — служебное слово Postgres)."""

    __tablename__ = "app_user"
    id: Mapped[uuid.UUID] = _id()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    created_at: Mapped[datetime] = _created()


class Membership(Base):
    __tablename__ = "membership"
    studio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("studio.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20))  # owner | designer | installer


class StudioProfile(Base):
    """Профиль студии — то, что сейчас лежит в projects/studio.yaml."""

    __tablename__ = "studio_profile"
    studio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("studio.id", ondelete="CASCADE"), primary_key=True
    )
    organization: Mapped[str] = mapped_column(Text, default="")
    stage: Mapped[str] = mapped_column(String(40), default="")
    signatures: Mapped[list[Any]] = mapped_column(default=list)
    studio: Mapped[Studio] = relationship(back_populates="profile")


class Symbol(Base):
    """Образец УГО студии для распознавания точек электрики на листах."""

    __tablename__ = "symbol"
    id: Mapped[uuid.UUID] = _id()
    studio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("studio.id", ondelete="CASCADE"))
    point_type: Mapped[str] = mapped_column(String(40))  # socket | switch | …
    object_key: Mapped[str] = mapped_column(Text)


# --- Проект и источники -------------------------------------------------------------


class Project(Base):
    __tablename__ = "project"
    id: Mapped[uuid.UUID] = _id()
    studio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("studio.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    # Состояние — значения service.models.ProjectState
    state: Mapped[str] = mapped_column(String(20), default="created")
    message: Mapped[str] = mapped_column(Text, default="")
    round: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    studio: Mapped[Studio] = relationship(back_populates="projects")
    sources: Mapped[list[Source]] = relationship(back_populates="project")


class Source(Base):
    __tablename__ = "source"
    __table_args__ = (UniqueConstraint("project_id", "sha256"),)
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    file_name: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))  # vector | raster | image | text | sketch
    pages: Mapped[int] = mapped_column(Integer, default=0)
    object_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    project: Mapped[Project] = relationship(back_populates="sources")


class FactsPage(Base):
    """Выжимка страницы источника (facts.analysis.to_dict) — кэш по хешу и версии алгоритма.
    Сводка (масштаб, число размеров, уверенность) — колонками: по ней работает порог
    «не удалось» и запросы по всем проектам."""

    __tablename__ = "facts_page"
    __table_args__ = (UniqueConstraint("source_id", "page", "algo_version"),)
    id: Mapped[uuid.UUID] = _id()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id", ondelete="CASCADE"))
    page: Mapped[int] = mapped_column(Integer)
    algo_version: Mapped[str] = mapped_column(String(20))
    adapter: Mapped[str] = mapped_column(String(10))  # vector | raster
    unit: Mapped[str] = mapped_column(String(4))
    scale_mm: Mapped[float | None] = mapped_column(Float)
    scale_dims: Mapped[int] = mapped_column(Integer, default=0)
    dims_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    facts: Mapped[dict[str, Any]] = mapped_column()
    created_at: Mapped[datetime] = _created()


# --- Модель, вопросы, сборки ------------------------------------------------------


class ModelVersion(Base):
    """Версия модели проекта: тексты YAML, кто и когда их записал."""

    __tablename__ = "model_version"
    __table_args__ = (UniqueConstraint("project_id", "version"),)
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    room_yaml: Mapped[str | None] = mapped_column(Text)
    electrical_yaml: Mapped[str | None] = mapped_column(Text)
    intake_yaml: Mapped[str | None] = mapped_column(Text)
    answers_yaml: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(20))  # analyzer | user | operator
    created_at: Mapped[datetime] = _created()


class Round(Base):
    __tablename__ = "round"
    __table_args__ = (UniqueConstraint("project_id", "number"),)
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_version.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class Question(Base):
    __tablename__ = "question"
    __table_args__ = (UniqueConstraint("round_id", "qid"),)
    id: Mapped[uuid.UUID] = _id()
    round_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("round.id", ondelete="CASCADE"))
    qid: Mapped[str] = mapped_column(String(20))  # q1, q2… из intake.yaml
    stage: Mapped[str] = mapped_column(String(20))
    target: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(10))  # critical | major | minor
    text: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="open")  # open | answered | …


class Answer(Base):
    __tablename__ = "answer"
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question.id", ondelete="CASCADE"), primary_key=True
    )
    value: Mapped[dict[str, Any]] = mapped_column()  # {"value": 1800} | {"accept": true} | …
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class Build(Base):
    """Прогон build_project по версии модели: отчёт (report.json) и статус."""

    __tablename__ = "build"
    id: Mapped[uuid.UUID] = _id()
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_version.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(20))  # built | insufficient | failed
    report: Mapped[dict[str, Any]] = mapped_column()
    created_at: Mapped[datetime] = _created()
    files: Mapped[list[BuildFile]] = relationship(back_populates="build")


class BuildFile(Base):
    """Файл сборки: dxf, epd, png, estimate, csv — сам файл в объектном хранилище."""

    __tablename__ = "build_file"
    id: Mapped[uuid.UUID] = _id()
    build_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("build.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(Text)  # путь внутри out/: project.dxf, estimate.csv…
    object_key: Mapped[str] = mapped_column(Text)
    build: Mapped[Build] = relationship(back_populates="files")


class PriceList(Base):
    """Прайс проекта — то, что сейчас лежит в prices.yaml."""

    __tablename__ = "price_list"
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), primary_key=True
    )
    currency: Mapped[str] = mapped_column(String(8), default="грн")
    date: Mapped[str] = mapped_column(String(20), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    items: Mapped[dict[str, Any]] = mapped_column(default=dict)
    board_kit: Mapped[list[Any]] = mapped_column(default=list)


class Usage(Base):
    """Расход LLM — то, что сейчас пишется в usage.jsonl проекта; основа биллинга."""

    __tablename__ = "usage"
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    round: Mapped[int] = mapped_column(Integer)
    backend: Mapped[str] = mapped_column(String(20))  # claude-code | api
    model: Mapped[str] = mapped_column(String(60), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 4, asdecimal=False), default=0)
    created_at: Mapped[datetime] = _created()
