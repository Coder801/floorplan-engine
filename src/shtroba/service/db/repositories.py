"""Доступ к базе для сервиса: проекты, источники, кэш выжимок, версии модели, расход LLM.

Функции получают открытую Session и не делают commit — транзакцией управляет вызывающий
(одна операция Workflow — одна транзакция).
"""

from __future__ import annotations

import hashlib
import statistics
import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shtroba.service.db.models import (
    FactsPage,
    ModelVersion,
    Project,
    Source,
    Studio,
    Usage,
)
from shtroba.service.facts.analysis import ALGO_VERSION, PageFacts, from_dict, to_dict

MODEL_COLUMNS = {
    "room.yaml": "room_yaml",
    "electrical.yaml": "electrical_yaml",
    "intake.yaml": "intake_yaml",
    "answers.yaml": "answers_yaml",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def create_studio(session: Session, name: str) -> Studio:
    studio = Studio(name=name)
    session.add(studio)
    session.flush()
    return studio


def create_project(session: Session, studio_id: uuid.UUID, name: str) -> Project:
    project = Project(studio_id=studio_id, name=name)
    session.add(project)
    session.flush()
    return project


def add_source(
    session: Session,
    project_id: uuid.UUID,
    file_name: str,
    data: bytes,
    kind: str,
    object_key: str,
    pages: int = 0,
) -> Source:
    """Источник проекта; тот же файл (по хешу) второй раз не добавляется — вернётся прежний."""
    digest = sha256(data)
    same = session.scalar(
        select(Source).where(Source.project_id == project_id, Source.sha256 == digest)
    )
    if same is not None:
        return same
    source = Source(
        project_id=project_id,
        file_name=file_name,
        sha256=digest,
        kind=kind,
        pages=pages,
        object_key=object_key,
    )
    session.add(source)
    session.flush()
    return source


def save_facts(session: Session, source_id: uuid.UUID, pages: Sequence[PageFacts]) -> None:
    """Выжимка источника текущей версии алгоритма: JSON и сводка колонками."""
    for f in pages:
        confidence = statistics.mean(d.confidence for d in f.dimensions) if f.dimensions else 0.0
        session.add(
            FactsPage(
                source_id=source_id,
                page=f.page,
                algo_version=ALGO_VERSION,
                adapter=f.source,
                unit=f.unit,
                scale_mm=f.scale,
                scale_dims=f.scale_dims,
                dims_count=len(f.dimensions),
                confidence=confidence,
                facts=to_dict(f),
            )
        )
    session.flush()


def cached_facts(session: Session, source_id: uuid.UUID) -> list[PageFacts] | None:
    """Выжимка из кэша, если её считала текущая версия алгоритма; None — считать заново."""
    rows = session.scalars(
        select(FactsPage)
        .where(FactsPage.source_id == source_id, FactsPage.algo_version == ALGO_VERSION)
        .order_by(FactsPage.page)
    ).all()
    return [from_dict(r.facts) for r in rows] or None


def add_model_version(
    session: Session, project_id: uuid.UUID, files: dict[str, str], author: str
) -> ModelVersion:
    """Новая версия модели: тексты YAML по именам файлов (room.yaml…); номер — следующий."""
    unknown = sorted(set(files) - set(MODEL_COLUMNS))
    if unknown:
        raise ValueError(f"не файлы модели: {', '.join(unknown)}")
    last = session.scalar(
        select(func.max(ModelVersion.version)).where(ModelVersion.project_id == project_id)
    )
    version = ModelVersion(project_id=project_id, version=(last or 0) + 1, author=author)
    for name, text in files.items():
        setattr(version, MODEL_COLUMNS[name], text)
    session.add(version)
    session.flush()
    return version


def latest_model(session: Session, project_id: uuid.UUID) -> ModelVersion | None:
    return session.scalar(
        select(ModelVersion)
        .where(ModelVersion.project_id == project_id)
        .order_by(ModelVersion.version.desc())
        .limit(1)
    )


def model_files(version: ModelVersion) -> dict[str, str]:
    """Файлы модели версии — чтобы выложить их в рабочую папку перед сборкой."""
    out = {}
    for name, column in MODEL_COLUMNS.items():
        text = getattr(version, column)
        if text is not None:
            out[name] = text
    return out


def record_usage(
    session: Session,
    project_id: uuid.UUID,
    round_no: int,
    backend: str,
    cost_usd: float,
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> Usage:
    usage = Usage(
        project_id=project_id,
        round=round_no,
        backend=backend,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
    session.add(usage)
    session.flush()
    return usage


def project_cost(session: Session, project_id: uuid.UUID) -> float:
    total = session.scalar(select(func.sum(Usage.cost_usd)).where(Usage.project_id == project_id))
    return float(total or 0.0)
