"""База сервиса: схема и репозитории на SQLite в памяти (Postgres в тестах не нужен)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from shtroba.service.db import repositories as repo
from shtroba.service.db.models import Base
from shtroba.service.db.session import create_tables, make_engine, make_sessions
from shtroba.service.facts.analysis import Dimension, PageFacts


@pytest.fixture
def session() -> Iterator[Session]:
    engine = make_engine("sqlite://")
    create_tables(engine)
    with make_sessions(engine)() as s:
        yield s


def test_schema_has_all_tables() -> None:
    expected = {
        "studio", "app_user", "membership", "studio_profile", "symbol", "project", "source",
        "facts_page", "model_version", "round", "question", "answer", "build", "build_file",
        "price_list", "usage",
    }  # fmt: skip
    assert set(Base.metadata.tables) == expected


def test_source_is_not_added_twice(session: Session) -> None:
    project = repo.create_project(session, repo.create_studio(session, "Студія").id, "Кв 1")
    a = repo.add_source(session, project.id, "plan.pdf", b"%PDF-1", "vector", "src/a")
    b = repo.add_source(session, project.id, "copy.pdf", b"%PDF-1", "vector", "src/b")
    assert a.id == b.id and a.sha256 == repo.sha256(b"%PDF-1")


def test_facts_cache_round_trip(session: Session) -> None:
    project = repo.create_project(session, repo.create_studio(session, "С").id, "Кв")
    source = repo.add_source(session, project.id, "plan.pdf", b"x", "vector", "k")
    assert repo.cached_facts(session, source.id) is None  # ещё не считали
    page = PageFacts(
        "plan.pdf", 1, 600, 400, scale=10.0, scale_dims=3,
        dimensions=[Dimension(1000, "h", 300, 50, 150, chain=1, drawn=1000.0, confidence=0.9)],
    )  # fmt: skip
    repo.save_facts(session, source.id, [page])
    assert repo.cached_facts(session, source.id) == [page]


def test_model_versions_increment_and_restore(session: Session) -> None:
    project = repo.create_project(session, repo.create_studio(session, "С").id, "Кв")
    v1 = repo.add_model_version(session, project.id, {"room.yaml": "name: A\n"}, "analyzer")
    v2 = repo.add_model_version(
        session, project.id, {"room.yaml": "name: B\n", "answers.yaml": "answers: {}\n"}, "user"
    )
    assert (v1.version, v2.version) == (1, 2)
    latest = repo.latest_model(session, project.id)
    assert latest is not None and repo.model_files(latest) == {
        "room.yaml": "name: B\n",
        "answers.yaml": "answers: {}\n",
    }
    with pytest.raises(ValueError, match="не файлы модели"):
        repo.add_model_version(session, project.id, {"notes.md": "…"}, "user")


def test_usage_sums_per_project(session: Session) -> None:
    project = repo.create_project(session, repo.create_studio(session, "С").id, "Кв")
    repo.record_usage(session, project.id, 1, "api", 1.25, input_tokens=1000)
    repo.record_usage(session, project.id, 2, "api", 0.5)
    assert repo.project_cost(session, project.id) == pytest.approx(1.75)
